"""CEO-observability alert push (v8 M21). Runs as the `ops-alerts` pseudo-kind on the
admin agent — a fleet health tick that proactively DMs the CEO when an agent goes quiet
or starts failing, so a low-tech operator learns about a dead agent without opening a
dashboard.

Deterministic + CODE-only (no LLM): reuses `team_alerts` (the same bar the /api/team/alerts
panel shows) and pushes any NEW-today alert to the admin's `ops_operator_id` through the
Action Gateway — no new outbound path. Dedup is per (agent, alert-kind, local-date) via the
gateway's dedup store (persists across restart), so a still-failing agent is re-notified once
the next day, never twice the same day.

Residual (documented, red-team M6): this is itself an agent run dispatched by the service. If
the ADMIN agent or the service daemon is the thing that died, no alert fires — M21 catches a
NORMAL agent dying while service + admin stay healthy. A dead-man's-switch is a follow-up.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

#: The alert kinds M21 pushes proactively. The pre-existing budget/approval/deny alerts stay
#: dashboard-only for now (they trend slowly; the panel is enough) — the new "agent chết
#: ngầm" signals are the ones a CEO must be interrupted for.
_PUSH_KINDS = frozenset({"missed_schedule", "failing"})

_SEVERITY_ICON = {"high": "🔴", "warn": "🟡"}


def run_ops_alerts(loaded, settings, *, now: datetime | None = None) -> dict:
    """One fleet-health tick. Returns a run-event dict for the worker (like run_tasks).

    Computes team_alerts over the whole fleet, keeps the push-worthy + not-yet-sent-today
    ones, and DMs the CEO a single combined message (one message even for N agents — no
    alert storm when the service was down overnight)."""
    from pathlib import Path

    from my_crew.actions.action_gateway import ActionGateway
    from my_crew.actions.dedup_store import DedupStore
    from my_crew.actions.telegram_write import send_telegram_message
    from my_crew.runtime.agent_state_reader import team_alerts

    telegram = loaded.config.telegram
    operator = getattr(telegram, "ops_operator_id", "") if telegram else ""
    if not telegram or not operator:
        # No CEO DM configured on this agent — nothing to push to. Not an error.
        return {"status": "no_operator", "checked": 0, "cost_usd": None, "delivered": False}

    now = now or datetime.now(UTC)
    alerts = [a for a in team_alerts(now=now) if a["kind"] in _PUSH_KINDS]

    if settings.write_disabled:
        logger.warning("ops-alerts %s: AGENT_WRITE_DISABLED — %d alert(s) not pushed",
                       loaded.profile_id, len(alerts))
        return {"status": "writes_disabled", "checked": len(alerts), "cost_usd": None,
                "delivered": False}

    local_date = now.astimezone().date().isoformat()  # local day — matches operator's clock
    # Per-alert dedup uses the admin's own dedup store (SQLite, survives restart) so the
    # same (agent, kind) is pushed at most once per local day. Claimed BEFORE sending so a
    # crash mid-send doesn't re-notify — acceptable: a missed push resurfaces tomorrow.
    dedup = DedupStore(Path(settings.data_dir) / "dedup.db")
    gateway = ActionGateway(
        settings, external_channels=loaded.config.slack_external_channels,
        actor=getattr(loaded, "profile_id", ""),  # v46
    )
    try:
        fresh = [a for a in alerts
                 if dedup.claim(f"ops-alert:{a['agent_id']}:{a['kind']}:{local_date}")]
        if not fresh:
            return {"status": "no_new_alerts", "checked": len(alerts), "cost_usd": None,
                    "delivered": False}
        # Distinct push key so the combined send is never gateway-deduped away (the
        # per-alert claims above already guaranteed freshness).
        push_key = "|".join(sorted(f"{a['agent_id']}:{a['kind']}" for a in fresh))
        result = send_telegram_message(
            _format(fresh),
            gateway=gateway,
            telegram=telegram,
            chat_id=operator,
            dedup_hint=f"ops-alerts-push:{local_date}:{push_key}",
            rationale="CEO-observability: agent health alert",
        )
        delivered = result.status in ("executed", "pending_approval")
        return {"status": "delivered" if delivered else result.status,
                "checked": len(alerts), "cost_usd": None, "delivered": delivered}
    finally:
        dedup.close()
        gateway.close()


def _format(alerts: list[dict]) -> str:
    """One combined Vietnamese message body for the CEO."""
    lines = ["⚠️ Cảnh báo sức khỏe đội agent:"]
    for a in alerts:
        icon = _SEVERITY_ICON.get(a["severity"], "•")
        lines.append(f"{icon} {a['agent_id']}: {a['message']}")
    lines.append("\nXem chi tiết ở mục Đội trên dashboard.")
    return "\n".join(lines)
