"""Per-minute reminder delivery sweep (v65) — the `reminder-sweep` pseudo-kind body.

No LLM ever runs here: read due pending rows, send each over the agent's OWN Telegram
through the Action Gateway (`telegram_send` — its two-way chat_ids allowlist + secret
scan re-gate the delivery; `dedup_hint` makes a crashed-after-send retry a clean
`deduplicated` no-op), mark sent. Mirrors `run_ops_alerts`'s gateway construction so a
reminder rides the exact same audited door every other outbound Telegram message does.

The kind is synthesized by `service._effective_schedule` ONLY while the agent has
pending rows (`reminder_store.has_pending_reminders`), so agents without reminders keep
a byte-identical schedule and this module never even loads for them.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def run_reminder_sweep(loaded: Any, settings: Any) -> dict:
    """One sweep: deliver every due reminder. Returns the run-event dict shape every
    other generic kind returns ({status, checked, cost_usd, delivered})."""
    from my_crew.actions.action_gateway import ActionGateway
    from my_crew.actions.telegram_write import send_telegram_message
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.reminder_store import ReminderStore, reminders_db_path

    agent_id = getattr(loaded, "profile_id", "")
    telegram = getattr(loaded.config, "telegram", None)
    store = ReminderStore(reminders_db_path(agent_data_dir(agent_id)))
    try:
        due = store.due()
        if not due:
            return {"status": "ok", "checked": 0, "cost_usd": None, "delivered": False}
        if telegram is None:
            # No transport: keep rows pending (honest — nothing was delivered) and let
            # the operator see the situation in logs rather than silently draining.
            logger.warning("reminder-sweep %s: %d due but no telegram config",
                           agent_id, len(due))
            return {"status": "no_transport", "checked": len(due), "cost_usd": None,
                    "delivered": False}

        gateway = ActionGateway(
            settings, external_channels=loaded.config.slack_external_channels,
            actor=agent_id,
        )
        delivered = 0
        for row in due:
            try:
                result = send_telegram_message(
                    f"⏰ Nhắc hẹn: {row['text']}",
                    gateway=gateway,
                    telegram=telegram,
                    chat_id=row["chat_id"],
                    dedup_hint=f"reminder:{row['id']}",
                    rationale=f"reminder #{row['id']} due at {row['due_at']}",
                )
            except Exception:  # noqa: BLE001 — one failed send must not wedge the rest
                logger.exception("reminder-sweep %s: send failed for #%s", agent_id, row["id"])
                continue
            # `executed` = went out now; `deduplicated` = already went out on a prior
            # attempt — both mean the CEO has (or had) the message: mark sent so the
            # row never fires again. A deny/queue outcome leaves it pending for the
            # next sweep (and the operator can see why in the audit log).
            if result.status in ("executed", "deduplicated"):
                store.mark_sent(row["id"])
                delivered += 1
        return {"status": "ok", "checked": len(due), "cost_usd": None,
                "delivered": delivered > 0}
    finally:
        store.close()
