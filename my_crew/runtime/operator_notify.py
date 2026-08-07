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
        from my_crew.actions.action_gateway import ActionGateway
        from my_crew.actions.telegram_write import send_telegram_message
        from my_crew.profile.loader import load_profile
        from my_crew.runtime.agent_paths import agent_data_dir
        from my_crew.runtime.registry import load_registry

        def _try_send(loaded) -> bool | None:
            """Send via one agent's binding; None = agent has no usable binding."""
            telegram = getattr(loaded.config, "telegram", None)
            operator = getattr(telegram, "ops_operator_id", "") if telegram else ""
            if not telegram or not operator:
                return None
            gw = ActionGateway(
                loaded.settings, external_channels=loaded.config.slack_external_channels,
                actor=getattr(loaded, "profile_id", ""),  # v46
            )
            try:
                result = send_telegram_message(
                    text, gateway=gw, telegram=telegram, chat_id=operator,
                    dedup_hint=dedup_hint, rationale=rationale, buttons=buttons,
                )
            finally:
                gw.close()
            return result.status in ("executed", "pending_approval", "dry_run")

        # CEO rule: "giao việc cho bot nào thì bot đó nhận mọi thông tin" — the
        # COORDINATOR's binding is the assigning chat, so it goes first. Observed live:
        # a clarify question landed in the admin ops chat while the CEO watched the
        # conversation they gave the task in. Admin stays the fallback.
        try:
            from my_crew.runtime.company import load_company

            coordinator_id = getattr(load_company(), "coordinator_id", "") or ""
        except Exception:  # noqa: BLE001 — no company config ⇒ straight to admin scan
            coordinator_id = ""
        if coordinator_id:
            try:
                coord = load_profile(coordinator_id, data_dir=agent_data_dir(coordinator_id))
                sent = _try_send(coord)
                if sent is not None:
                    return sent
            except Exception:  # noqa: BLE001 — coordinator problems must not kill the notice
                logger.warning("operator notice: coordinator path failed", exc_info=True)

        for entry in load_registry():
            try:
                admin = load_profile(entry.id, data_dir=agent_data_dir(entry.id))
            except Exception:  # noqa: BLE001 — a broken profile must not kill the scan
                continue
            if getattr(admin, "domain", "") != "admin":
                continue
            sent = _try_send(admin)
            if sent is not None:
                return sent
        logger.info("operator notice skipped — no admin ops agent configured")
        return False
    except Exception:  # noqa: BLE001 — a notice is an overlay, never the caller's fate
        logger.warning("operator notice failed", exc_info=True)
        return False
