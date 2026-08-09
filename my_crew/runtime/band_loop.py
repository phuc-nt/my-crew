"""Closed loop: metrics → autonomy band, asymmetric (v76 phase 3).

my-dandori's rule, kept exactly: **tightening is automatic, loosening past the default
needs a human, ambiguity only ever produces a PROPOSAL.** Per 14-day window:

  - clearly bad  (needs_decision rate ≥ fleet p90 AND its CI-low above the fleet
    median — evidence, not noise) → auto-demote to `supervised`;
  - somewhat bad (≥ p75, not clearly) → a Telegram PROPOSAL for the CEO (`set_band`),
    the loop itself changes nothing;
  - recovered    (a supervised agent whose CI-high fell below the fleet median) →
    auto-promote back to `normal` — the return ticket is automatic so supervision
    never becomes a life sentence; `trusted` stays CEO-only (loosening past default).

Discipline gates (each one a tested refusal, not a comment): tentative metrics
(n < MIN_SAMPLE) are never acted on; fewer than 3 comparable agents means no fleet to
rank against; a band changed in the last `COOLDOWN_DAYS` is left alone (no thrash).
Every change/proposal is audited with its FORMULA (rate, CI, thresholds) and mirrored
to the CEO — the system never re-scopes anyone silently.

Runs inside the team-tick hygiene block at most once per hour (marker-file gate) —
plan invariant: this loop reads metrics and writes bands, nothing else; dispatch,
budgets, the gateway, and the autopilot ladder are out of its reach.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

DEMOTE_PCTL = 0.90
PROPOSE_PCTL = 0.75
COOLDOWN_DAYS = 3
MIN_FLEET = 3
_MARKER = "band_loop.last_run"


def run_band_loop(*, force: bool = False) -> int:
    """One loop pass. Returns how many band CHANGES were made (proposals excluded).
    Never raises — this runs in the tick's hygiene block."""
    try:
        return _run(force=force)
    except Exception:  # noqa: BLE001 — hygiene, never the tick's fate
        logger.warning("band loop failed", exc_info=True)
        return 0


def _run(*, force: bool) -> int:
    from my_crew.config.settings import DATA_DIR
    from my_crew.runtime.agent_metrics import agent_metrics
    from my_crew.runtime.band_store import BAND_NORMAL, BAND_SUPERVISED, BandStore

    marker = DATA_DIR / _MARKER
    if not force and marker.exists():
        age_s = datetime.now(UTC).timestamp() - marker.stat().st_mtime
        if age_s < 3600:
            return 0
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()

    metrics = agent_metrics(window_days=14)
    if metrics.get("error"):
        return 0
    candidates = {
        aid: a["needs_decision_rate"]
        for aid, a in (metrics.get("agents") or {}).items()
        if not a.get("tentative") and a["needs_decision_rate"].get("value") is not None
    }
    if len(candidates) < MIN_FLEET:
        return 0  # no fleet to rank against — silence, not action

    values = sorted(r["value"] for r in candidates.values())
    median = values[len(values) // 2]
    p90 = values[min(len(values) - 1, int(round(DEMOTE_PCTL * (len(values) - 1))))]
    p75 = values[min(len(values) - 1, int(round(PROPOSE_PCTL * (len(values) - 1))))]

    changed = 0
    store = BandStore()
    try:
        for agent_id, rate in sorted(candidates.items()):
            if _in_cooldown(store, agent_id):
                continue
            band = store.get(agent_id)
            value, (ci_low, ci_high) = rate["value"], rate["ci"]
            formula = (f"needs_decision {value:.0%} (CI {ci_low:.0%}–{ci_high:.0%}, "
                       f"n={rate['n']}) vs fleet median {median:.0%} / p75 {p75:.0%} "
                       f"/ p90 {p90:.0%}, cửa sổ {metrics['window_days']} ngày")
            if band != BAND_SUPERVISED and value >= p90 and ci_low > median:
                store.set(agent_id, BAND_SUPERVISED,
                          reason=f"auto-demote: {formula}", changed_by="band-loop")
                _announce(agent_id, "band_demoted",
                          f"Siết giám sát {agent_id}: mọi bước sẽ được soát chéo — {formula}")
                changed += 1
            elif band != BAND_SUPERVISED and value >= p75:
                _announce(agent_id, "band_demote_proposed",
                          f"Đề xuất siết giám sát {agent_id} (CEO quyết, lệnh "
                          f"`set_band`): {formula}")
            elif band == BAND_SUPERVISED and ci_high < median:
                store.set(agent_id, BAND_NORMAL,
                          reason=f"auto-promote (hồi phục): {formula}",
                          changed_by="band-loop")
                _announce(agent_id, "band_promoted",
                          f"Gỡ giám sát {agent_id} — hiệu suất đã hồi phục: {formula}")
                changed += 1
    finally:
        store.close()
    return changed


def _in_cooldown(store, agent_id: str) -> bool:
    ts = store.updated_at(agent_id)
    if not ts:
        return False
    try:
        changed_at = datetime.fromisoformat(ts)
    except ValueError:
        return False
    return datetime.now(UTC) - changed_at < timedelta(days=COOLDOWN_DAYS)


def _announce(agent_id: str, milestone: str, message: str) -> None:
    """Office event + audit row + best-effort Telegram — a band decision is never
    silent (the my-dandori UX finding: a silent closed-loop demote reads as a bug)."""
    try:
        from my_crew.audit.audit_log import AuditEntry, AuditLog
        from my_crew.runtime.team_task_paths import team_tasks_root

        AuditLog(team_tasks_root() / "audit" / "audit.jsonl").record(AuditEntry(
            action_type="band_loop", tool=f"band:{agent_id}", verdict="allow",
            reason=milestone, rationale=message, actor="band-loop",
        ))
    except Exception:  # noqa: BLE001
        logger.warning("band loop: audit append failed", exc_info=True)
    try:
        from my_crew.runtime.office_room_append import append_office_event

        append_office_event(
            "office", author="coordinator", kind="milestone",
            body={"milestone": milestone, "agent_id": agent_id, "message": message},
            also_office=False,
        )
    except Exception:  # noqa: BLE001
        logger.warning("band loop: office event failed", exc_info=True)
    try:
        from my_crew.runtime.operator_notify import notify_operator_best_effort

        notify_operator_best_effort(
            message, dedup_hint=f"band-loop:{agent_id}:{milestone}",
            rationale="band loop decision mirror",
        )
    except Exception:  # noqa: BLE001
        logger.warning("band loop: operator notify failed", exc_info=True)
