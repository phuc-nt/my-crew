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

from src.llm.budget_tracker import _current_month
from src.profile.loader import load_profile
from src.runtime.agent_paths import agent_data_dir
from src.runtime.registry import load_registry
from src.runtime.run_event import read_last_run_event

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


def read_agent_state(agent_id: str) -> dict:
    """One agent's operational snapshot as a plain dict (JSON-able, no secrets).

    A broken profile degrades (name error string, cap 0) instead of raising — one bad
    agent must not blind the admin over the whole fleet.
    """
    data_dir = agent_data_dir(agent_id)
    try:
        loaded = load_profile(agent_id, data_dir=data_dir)
        name, cap = loaded.name, loaded.settings.monthly_budget_usd
        enabled = loaded.enabled
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
    }


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
    return alerts


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
