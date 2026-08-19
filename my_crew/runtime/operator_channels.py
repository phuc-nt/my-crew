"""Which CHANNEL an operator notice goes out on — email and webhook beside Telegram.

`operator_notify` decides WHICH AGENT speaks (coordinator first, then the admin ops
agent). This module decides HOW the words leave the building, and the two are separate
questions: an operator who does not use Telegram was previously unreachable no matter
which agent tried, because every path ended at `send_telegram_message`. The room
milestone mirror still held the content, but "it is in the web app if you go look" is
not a push — the whole point of an escalation is to reach someone who is NOT looking.

Channels are tried in order (Telegram, SMTP, webhook) and the first success wins. Each
reports "not configured" (None) separately from "failed" (False), so an unconfigured
channel is skipped in silence while a configured-but-broken one is logged loudly.

Config is env-presence-based, following `smtp_from_env`: a channel exists when its env
vars are set. Deliberately NOT in `company.yaml`, whose save path rebuilds the file
from a fixed dict and drops hand-written keys.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

#: Where webhook notices go. One generic JSON POST covers Discord, Slack, ntfy and any
#: self-hosted receiver, which is why this exists instead of one adapter per vendor.
OPERATOR_WEBHOOK_URL_ENV = "OPERATOR_WEBHOOK_URL"

#: Recipient for email notices. The SMTP *connection* is already configured (profile
#: `smtp:` block or SMTP_* env); this only says who the operator is. Falls back to the
#: configured report recipients, which are already a human's inbox.
OPERATOR_EMAIL_ENV = "OPERATOR_EMAIL"

#: Webhook timeout. Short on purpose: a notice is worth a moment, not a stalled tick,
#: and the room mirror already holds the content if this one misses.
WEBHOOK_TIMEOUT_S = 5.0

#: SMTP timeout. Larger than the webhook's — connect plus STARTTLS plus login is
#: legitimately slower than one POST — but still bounded, so a hung mail server cannot
#: wedge the runtime tick that called us.
SMTP_TIMEOUT_S = 15.0


def send_via_channels(
    text: str,
    *,
    loaded: Any,
    settings: Any = None,
    dedup_hint: str = "",
    rationale: str = "",
    buttons: list[dict[str, str]] | None = None,
    subject: str = "my-crew: thông báo vận hành",
) -> bool | None:
    """Push `text` for one agent over the first channel that works.

    Returns True when a channel accepted it, False when every configured channel was
    tried and none delivered, and None when this agent has NO channel configured at
    all. That third state is what lets the caller keep walking its agent list: "this
    agent cannot speak" is not the same answer as "the message could not be sent".
    """
    attempted = False
    for name, fn in (("telegram", _try_telegram), ("smtp", _try_smtp), ("webhook", _try_webhook)):
        try:
            outcome = fn(
                text, loaded=loaded, settings=settings, dedup_hint=dedup_hint,
                rationale=rationale, buttons=buttons, subject=subject,
            )
        except Exception:  # noqa: BLE001 — a broken channel must not block the next one
            logger.warning("operator notice: channel %s raised", name, exc_info=True)
            attempted = True
            continue
        if outcome is None:  # not configured — silence is correct, not a failure
            continue
        attempted = True
        if outcome:
            logger.info("operator notice delivered via %s", name)
            return True
        logger.warning("operator notice: channel %s is configured but did not deliver", name)
    return False if attempted else None


def _try_telegram(
    text: str, *, loaded: Any, settings: Any, dedup_hint: str, rationale: str,
    buttons: list[dict[str, str]] | None, **_: Any,
) -> bool | None:
    """DM through this agent's own binding. None when the agent has no binding."""
    telegram = getattr(loaded.config, "telegram", None)
    operator = getattr(telegram, "ops_operator_id", "") if telegram else ""
    if not telegram or not operator:
        return None

    from my_crew.actions.action_gateway import ActionGateway
    from my_crew.actions.telegram_write import send_telegram_message

    gw = ActionGateway(
        settings if settings is not None else loaded.settings,
        external_channels=loaded.config.slack_external_channels,
        actor=getattr(loaded, "profile_id", ""),
    )
    try:
        result = send_telegram_message(
            text, gateway=gw, telegram=telegram, chat_id=operator,
            dedup_hint=dedup_hint, rationale=rationale, buttons=buttons,
        )
    finally:
        gw.close()
    # `pending_approval` counts as delivered: the action sits in the CEO's approval
    # queue, so it HAS reached them — falling through to email would double-notify.
    # `dry_run` likewise: a rehearsing agent must not start sending real email.
    return result.status in ("executed", "pending_approval", "dry_run")


def _try_smtp(text: str, *, loaded: Any, subject: str, **_: Any) -> bool | None:
    """Plain email over the already-configured SMTP channel.

    Sent directly rather than through the ActionGateway: this is an internal notice to
    the fleet's own operator, not an outbound company action, so it is not a Lớp B
    write and must not queue for approval — a notice that needs approval before it can
    be delivered cannot do its job. The password is read from env at send time, exactly
    as the gateway's email handler does, so it never lands in a config object or a log.
    """
    smtp_cfg = getattr(loaded.config, "smtp", None)
    if not smtp_cfg or not smtp_cfg.smtp_host:
        return None
    explicit = os.environ.get(OPERATOR_EMAIL_ENV, "").strip()
    to = [explicit] if explicit else [
        str(r) for r in getattr(smtp_cfg, "recipients", ()) if str(r).strip()
    ]
    if not to:
        return None

    from my_crew.actions.email_write import send_plain_email

    send_plain_email(smtp_cfg, to=to, subject=subject, body=text, timeout=SMTP_TIMEOUT_S)
    return True


def _try_webhook(text: str, *, rationale: str, **_: Any) -> bool | None:
    """Generic JSON POST. None when `OPERATOR_WEBHOOK_URL` is unset.

    The payload carries `text` (what most receivers render), `content` (the key Discord
    reads) and `message`, so a single URL works for Discord, Slack, ntfy and hand-rolled
    receivers without a per-vendor adapter.
    """
    url = os.environ.get(OPERATOR_WEBHOOK_URL_ENV, "").strip()
    if not url:
        return None
    payload = json.dumps(
        {"text": text, "content": text, "message": text, "rationale": rationale}
    ).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 — operator-supplied URL, not user input
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=WEBHOOK_TIMEOUT_S) as resp:  # noqa: S310
        return 200 <= resp.status < 300


def channels_for(loaded: Any) -> list[str]:
    """Which push channels this agent can use right now, in try order.

    Read-only: the integration-health surface shows it so the operator can see whether
    the fleet can reach them at all, instead of finding out by never being told.
    """
    names: list[str] = []
    telegram = getattr(loaded.config, "telegram", None)
    if telegram and getattr(telegram, "ops_operator_id", ""):
        names.append("telegram")
    smtp_cfg = getattr(loaded.config, "smtp", None)
    if smtp_cfg and smtp_cfg.smtp_host and (
        os.environ.get(OPERATOR_EMAIL_ENV, "").strip()
        or any(str(r).strip() for r in getattr(smtp_cfg, "recipients", ()))
    ):
        names.append("smtp")
    if os.environ.get(OPERATOR_WEBHOOK_URL_ENV, "").strip():
        names.append("webhook")
    return names
