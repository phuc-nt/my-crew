"""Read-only cross-agent state accessor (v3 M8 S1). GENERIC — no domain logic.

The one core addition the admin pack needs: aggregate every registry agent's local
state (budget spent/cap, pending Lớp B approvals, recent audit verdicts, last run)
into plain dicts. Strictly READ-ONLY by construction: budget/audit/runs are file
reads; approvals open the SQLite store and only call `list_pending()` then close.
Nothing here can mutate another agent — cross-agent WRITE stays a red line (an admin
agent reads the fleet, it never approves/rejects/triggers a sibling).

Also backs the generic team-alerts API (M8 S5): `team_alerts()` applies fixed,
deterministic thresholds — no LLM, no domain wording.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from croniter import croniter

from my_crew.llm.budget_tracker import _current_month
from my_crew.profile.loader import load_profile
from my_crew.runtime.agent_paths import agent_data_dir
from my_crew.runtime.registry import load_registry
from my_crew.runtime.run_event import read_last_run_event

logger = logging.getLogger(__name__)

#: Bound file scans: only this many trailing audit lines are parsed per agent — an
#: agent with months of audit history must not make every admin run O(history).
_AUDIT_TAIL_LINES = 2000
_AUDIT_WINDOW_DAYS = 7

# Deterministic alert thresholds (S5). Fixed here, not per-profile — the point of the
# team view is one consistent bar across the fleet.
_BUDGET_ALERT_RATIO = 0.8
_APPROVAL_STUCK_HOURS = 24
_DENY_SPIKE_COUNT = 3  # >= this many denies inside the audit window

# v8 M21 — "agent chết ngầm" detection (CODE-only, no LLM):
#: A scheduled kind is "overdue" if its last run is older than max(2× its cron period,
#: this floor after the scheduled fire). Wide on purpose — a machine asleep / a service
#: restart near fire time must not cry wolf. See _overdue_kinds.
_OVERDUE_FLOOR_HOURS = 6
#: >= this many consecutive error/load_error run-events for one kind ⇒ a `failing` alert.
_FAILING_STREAK = 3
#: How many recent run-events to keep PER KIND for the failing streak / last-run check.
_FAILING_SCAN = 10
#: Trailing runs.jsonl lines scanned before the per-kind down-sample. Generous so a chatty
#: poller can't push a report kind out of view (matches the _AUDIT_TAIL_LINES bound style).
_RUN_EVENT_TAIL = 5000
#: Run-event statuses that count as a failure for the streak.
_FAILURE_STATUSES = frozenset({"error", "load_error"})
#: Kinds that are synthetic pollers, not scheduled reports — never "overdue" (a poll with
#: nothing to do is a success, and inbox/tasks fire on a fast synthetic cron).
#: v12 M28a: "team-step" is a per-step team-task run spawned on-demand by the P3
#: coordinator (not on the agent's own cron) — same non-report treatment.
#: v12 M28b: "team-tick" is the coordinator's own short poll (like ops-alerts) — same
#: non-report treatment.
#: v12 M29: "milestone-mirror" is the admin agent's office-room Telegram mirror poll —
#: same non-report treatment (a tick with nothing new to push is a success, not overdue).
_NON_REPORT_KINDS = frozenset(
    {"inbox", "tasks", "ops-alerts", "team-step", "team-tick", "milestone-mirror"}
)


def read_agent_state(agent_id: str) -> dict:
    """One agent's operational snapshot as a plain dict (JSON-able, no secrets).

    A broken profile degrades (name error string, cap 0) instead of raising — one bad
    agent must not blind the admin over the whole fleet.
    """
    data_dir = agent_data_dir(agent_id)
    schedule: dict[str, str] = {}
    reports: tuple[str, ...] = ()
    domain, project = "", None
    try:
        loaded = load_profile(agent_id, data_dir=data_dir)
        name, cap = loaded.name, loaded.settings.monthly_budget_usd
        enabled = loaded.enabled
        schedule = dict(loaded.schedule)
        reports = loaded.reports
        domain = getattr(loaded, "domain", "")
        # v8 M22: the agent's project identity for the portfolio roll-up (Jira key or repo).
        project = loaded.config.jira_project_key or loaded.config.github_repo
    except Exception as exc:  # noqa: BLE001 — ANY broken profile (missing file, bad
        # yaml, bad model_chain ValueError, …) degrades to an error row: one
        # misconfigured agent must never blind the admin over the whole fleet.
        logger.warning("agent %r profile unreadable in fleet view: %s", agent_id, exc)
        name, cap, enabled = f"<error: {exc}>", 0.0, False
    spent = _read_budget(data_dir)
    return {
        "agent_id": agent_id,
        "name": name,
        "enabled": enabled,
        "budget_spent_usd": spent,
        "budget_cap_usd": cap,
        "budget_ratio": (spent / cap) if cap > 0 else 0.0,
        "pending_approvals": _read_pending(data_dir),
        "audit_counts": _read_audit_counts(data_dir),
        "last_run": read_last_run_event(agent_id),
        # v8 M21: schedule + recent run history feed the missed_schedule / failing alerts.
        # PER-KIND window (not a global tail): a polling agent floods runs.jsonl with
        # inbox/tasks events between reports, so a global limit would evict every report
        # event and blind both alerts. We keep the newest _FAILING_SCAN events of EACH kind.
        "schedule": schedule,
        "reports": reports,
        "run_events": _recent_events_per_kind(agent_id),
        # v8 M22: domain + project identity for the portfolio roll-up.
        "domain": domain,
        "project": project,
    }


def _recent_events_per_kind(agent_id: str) -> list[dict]:
    """Newest-first run-events, keeping at most `_FAILING_SCAN` per kind.

    Scans a bounded TAIL of runs.jsonl and down-samples per kind so a chatty poller
    (`inbox`/`tasks` fire every few minutes) can't evict the report events a global tail
    would drop — the defect a single-limit read caused. The tail bound (`_RUN_EVENT_TAIL`)
    is generous: even a 1-minute poller leaves report events within it for well over a day."""
    path = agent_data_dir(agent_id) / "runs.jsonl"
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-_RUN_EVENT_TAIL:]
    except OSError:
        return []
    per_kind: dict[str, int] = {}
    kept: list[dict] = []
    for line in reversed(lines):  # newest-first
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = ev.get("kind")
        if not kind:
            continue
        n = per_kind.get(kind, 0)
        if n < _FAILING_SCAN:
            per_kind[kind] = n + 1
            kept.append(ev)
    return kept


def read_all_agent_states() -> list[dict]:
    """Snapshot every registry agent (enabled or not — the admin sees the whole fleet)."""
    return [read_agent_state(entry.id) for entry in load_registry()]


def team_alerts(states: list[dict] | None = None, *, now: datetime | None = None) -> list[dict]:
    """Deterministic fleet alerts: budget near cap, stuck approvals, deny spikes.

    Each alert: {kind, agent_id, message, severity} — plain data for the API/UI and
    for the admin pack's analyzers alike.
    """
    states = states if states is not None else read_all_agent_states()
    now = now or datetime.now(UTC)
    alerts: list[dict] = []
    for s in states:
        if s["budget_cap_usd"] > 0 and s["budget_ratio"] >= _BUDGET_ALERT_RATIO:
            alerts.append(_alert(
                "budget", s["agent_id"],
                f"budget at {s['budget_ratio']:.0%} of ${s['budget_cap_usd']:.2f} cap",
                "high" if s["budget_ratio"] >= 1.0 else "warn",
            ))
        for p in s["pending_approvals"]:
            age_h = _age_hours(p.get("created_at"), now)
            if age_h is not None and age_h >= _APPROVAL_STUCK_HOURS:
                alerts.append(_alert(
                    "approval_stuck", s["agent_id"],
                    f"approval #{p['id']} pending for {age_h:.0f}h ({p.get('reason', '')})",
                    "warn",
                ))
        denies = s["audit_counts"].get("deny", 0)
        if denies >= _DENY_SPIKE_COUNT:
            alerts.append(_alert(
                "deny_spike", s["agent_id"],
                f"{denies} gateway denies in the last {_AUDIT_WINDOW_DAYS} days",
                "high",
            ))
        # v8 M21 — "agent chết ngầm". Only for an effectively-enabled agent: a disabled
        # agent is SUPPOSED to be silent (a paused agent isn't "dead"). States coming from
        # older callers without schedule/run_events simply skip these (backward-compat).
        if s.get("enabled"):
            for kind in _overdue_kinds(s, now):
                alerts.append(_alert(
                    "missed_schedule", s["agent_id"],
                    f"báo cáo '{kind}' quá hạn — chưa chạy đúng lịch",
                    "high",
                ))
            for kind in _failing_kinds(s):
                alerts.append(_alert(
                    "failing", s["agent_id"],
                    f"báo cáo '{kind}' lỗi {_FAILING_STREAK} lần liên tiếp",
                    "high",
                ))
    return alerts


def _overdue_kinds(state: dict, now: datetime) -> list[str]:
    """Scheduled report kinds whose last run is older than the overdue threshold.

    Threshold = max(2× the cron period, `_OVERDUE_FLOOR_HOURS`) after the most recent
    scheduled fire at/before `now`. Wide by design: a machine asleep or a service restart
    near fire time must not false-alarm. A never-run scheduled kind is overdue once its
    first scheduled fire is older than the floor. Only kinds also in the `reports` gate and
    not synthetic pollers are considered."""
    schedule = state.get("schedule") or {}
    reports = state.get("reports") or ()
    last_by_kind = _last_run_ts_by_kind(state.get("run_events") or [])
    overdue: list[str] = []
    for kind, cron in schedule.items():
        if kind in _NON_REPORT_KINDS:
            continue
        if reports and kind not in reports:
            continue
        if not croniter.is_valid(cron):
            continue
        threshold_h = max(_cron_period_hours(cron) * 2, _OVERDUE_FLOOR_HOURS)
        prev_fire = _prev_fire(cron, now)
        if prev_fire is None:
            continue
        last_ts = last_by_kind.get(kind)
        # Never ran: overdue only once the first scheduled fire itself is past the floor
        # (a freshly-created agent isn't instantly "dead").
        reference = last_ts if last_ts is not None else prev_fire
        age_h = (now - reference).total_seconds() / 3600.0
        if age_h >= threshold_h:
            overdue.append(kind)
    return overdue


def _failing_kinds(state: dict) -> list[str]:
    """Report kinds whose most recent run-events are `_FAILING_STREAK` consecutive failures.

    Reads newest-first `run_events`; for each kind, counts the leading failure streak among
    that kind's events. A worker that HANGS writes no terminal event, so a hang surfaces as
    missed_schedule, not failing (documented limitation)."""
    events = state.get("run_events") or []
    streak: dict[str, int] = {}
    broken: set[str] = set()
    failing: list[str] = []
    for ev in events:  # newest-first
        kind = ev.get("kind")
        if not kind or kind in _NON_REPORT_KINDS or kind in broken:
            continue
        if str(ev.get("status")) in _FAILURE_STATUSES:
            streak[kind] = streak.get(kind, 0) + 1
            if streak[kind] >= _FAILING_STREAK and kind not in failing:
                failing.append(kind)
        else:
            broken.add(kind)  # a success breaks the leading streak for this kind
    return failing


def _last_run_ts_by_kind(events: list[dict]) -> dict[str, datetime]:
    """Newest run-event timestamp per kind (events are newest-first)."""
    out: dict[str, datetime] = {}
    for ev in events:
        kind = ev.get("kind")
        if not kind or kind in out:
            continue
        ts = _parse_ts(ev.get("ts"))
        if ts is not None:
            out[kind] = ts
    return out


def _parse_ts(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts


def _cron_period_hours(cron: str) -> float:
    """Approx hours between two consecutive fires of `cron` (from a fixed base)."""
    try:
        base = datetime(2000, 1, 3, tzinfo=UTC)  # a Monday, deterministic
        it = croniter(cron, base)
        first = it.get_next(datetime)
        second = it.get_next(datetime)
        return (second - first).total_seconds() / 3600.0
    except (ValueError, KeyError):
        return _OVERDUE_FLOOR_HOURS


def _prev_fire(cron: str, now: datetime) -> datetime | None:
    """The most recent scheduled fire at/before `now`, interpreting the cron in LOCAL time.

    The service scheduler fires crons on naive LOCAL time (`"0 8 * * *"` = 08:00 local), so
    the overdue check must resolve fires the same way — otherwise a UTC interpretation skews
    the reference point by the UTC offset. `now` is converted to local-aware; croniter then
    honors that tz, and the result stays tz-aware so age math against `now` is exact."""
    try:
        local_now = now.astimezone()
        return croniter(cron, local_now).get_prev(datetime)
    except (ValueError, KeyError):
        return None


def _alert(kind: str, agent_id: str, message: str, severity: str) -> dict:
    return {"kind": kind, "agent_id": agent_id, "message": message, "severity": severity}


def _age_hours(created_at: str | None, now: datetime) -> float | None:
    if not created_at:
        return None
    try:
        created = datetime.fromisoformat(str(created_at))
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (now - created).total_seconds() / 3600.0


def _read_budget(data_dir: Path) -> float:
    """This month's spend from the budget file (same file BudgetTracker writes)."""
    path = data_dir / "budget" / f"budget-{_current_month()}.json"
    if not path.exists():
        return 0.0
    try:
        return float(json.loads(path.read_text(encoding="utf-8")).get("total_usd", 0.0))
    except (json.JSONDecodeError, TypeError, ValueError, OSError):
        logger.warning("unreadable budget file %s — treating as 0", path)
        return 0.0


def _read_pending(data_dir: Path) -> list[dict]:
    """Pending Lớp B approvals — id/reason/created_at only (action stays out: it may be
    large and the fleet view needs the queue shape, not the payloads).

    Opened READ-ONLY (`mode=ro`) on purpose: ApprovalStore's constructor runs DDL,
    which would WRITE schema into a sibling's data dir — the admin reads the fleet, it
    never mutates it. Any sqlite failure (corrupt/locked/schema-less db) degrades to
    an empty list with a warning instead of blinding the whole fleet view.
    """
    db = data_dir / "approvals.db"
    if not db.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT id, reason, created_at FROM approvals "
                "WHERE status = 'pending' ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("approvals db unreadable at %s: %s", db, exc)
        return []
    return [{"id": r[0], "reason": r[1], "created_at": r[2]} for r in rows]


def _read_audit_counts(data_dir: Path) -> dict[str, int]:
    """Verdict counts over the audit window from the tail of audit.jsonl."""
    path = data_dir / "audit" / "audit.jsonl"
    if not path.exists():
        return {}
    since = datetime.now(UTC) - timedelta(days=_AUDIT_WINDOW_DAYS)
    counts: dict[str, int] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-_AUDIT_TAIL_LINES:]
    except OSError:
        return {}
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts_raw = entry.get("timestamp")
        try:
            ts = datetime.fromisoformat(str(ts_raw)) if ts_raw else None
        except ValueError:
            ts = None
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts is not None and ts < since:
            continue
        verdict = str(entry.get("verdict") or "unknown")
        counts[verdict] = counts.get(verdict, 0) + 1
    return counts
