"""Best-effort CEO Telegram notice from ANY runtime context (v31).

One shared helper for code that must tell the operator something happened but is not
running as the admin agent (a schedule_update handler on a line agent, a watcher's
fail/stale alert): scan the registry for the admin ops agent (domain "admin" +
`telegram.ops_operator_id`), and send the message through THAT agent's own Action
Gateway — the same v21 ops-DM path `ops_alert_runner` uses, so the notice is audited
under the admin agent like every other operator DM. Best-effort by contract: a notice
failure is logged, never raised — the caller's real work must not fail on messaging.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def notify_operator_best_effort(
    text: str, *, dedup_hint: str, rationale: str,
    buttons: list[dict[str, str]] | None = None,
) -> bool:
    """DM the CEO via the admin ops agent's gateway. Returns True when handed off.

    False means "no admin ops agent configured" or the send failed — both logged,
    neither raised. `buttons` (v33 P4) rides through to the telegram send as inline
    answer buttons — same gateway, same audit.
    """
    try:
        from src.actions.action_gateway import ActionGateway
        from src.actions.telegram_write import send_telegram_message
        from src.profile.loader import load_profile
        from src.runtime.agent_paths import agent_data_dir
        from src.runtime.registry import load_registry

        for entry in load_registry():
            try:
                admin = load_profile(entry.id, data_dir=agent_data_dir(entry.id))
            except Exception:  # noqa: BLE001 — a broken profile must not kill the scan
                continue
            telegram = getattr(admin.config, "telegram", None)
            operator = getattr(telegram, "ops_operator_id", "") if telegram else ""
            if getattr(admin, "domain", "") != "admin" or not operator:
                continue
            gw = ActionGateway(
                admin.settings, external_channels=admin.config.slack_external_channels,
                actor=getattr(admin, "profile_id", ""),  # v46
            )
            try:
                result = send_telegram_message(
                    text, gateway=gw, telegram=telegram, chat_id=operator,
                    dedup_hint=dedup_hint, rationale=rationale, buttons=buttons,
                )
            finally:
                gw.close()
            return result.status in ("executed", "pending_approval", "dry_run")
        logger.info("operator notice skipped — no admin ops agent configured")
        return False
    except Exception:  # noqa: BLE001 — a notice is an overlay, never the caller's fate
        logger.warning("operator notice failed", exc_info=True)
        return False
