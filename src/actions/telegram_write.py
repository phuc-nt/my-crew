"""Telegram WRITE — send a message via the Action Gateway (v6 M13).

Outbound Telegram is a MUTATION, so it MUST go through `ActionGateway.execute`, never
call the Bot API directly outside the handler. The gateway applies the `telegram_send`
Lớp A scan (secrets, structural validity), kill-switch, dry-run, rate-limit, idempotency,
and audit. Unlike email (all Lớp B), a telegram send to a CONFIGURED chat executes
directly — the `chat_ids` allowlist is operator-declared per agent, the same trust level
as an internal Slack channel.

The chat allowlist is enforced HERE, at the runtime execution path: the handler is a
closure over the agent's `TelegramConfig` and refuses any chat_id outside `chat_ids`
(defense-in-depth on top of the read-side filter — a bot dragged into a stranger's group
can neither read nor speak there). The bot token is read from os.environ at send time by
the declared env NAME, so it never rides on the action dict / audit log / approval store.

stdlib only (`urllib.request`) — no new dependency, mirroring `email_write`.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from src.actions.action_gateway import ActionGateway, GatewayResult
from src.config.telegram_config import TelegramConfig
from src.config.telegram_token import resolve_bot_token

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], str]

_API_BASE = "https://api.telegram.org"
#: Telegram hard-caps messages at 4096 chars; truncate below it so the marker fits.
_MAX_TEXT_CHARS = 3900


def api_call(token: str, method: str, payload: dict[str, Any] | None = None) -> Any:
    """One Bot API call. POST JSON when a payload is given, GET otherwise.

    Raises RuntimeError on an API-level failure (ok=false) — the caller decides whether
    that is retryable. Network errors propagate as urllib exceptions.
    """
    url = f"{_API_BASE}/bot{token}/{method}"
    if payload is None:
        req = urllib.request.Request(url, method="GET")
    else:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    if not isinstance(out, dict) or not out.get("ok"):
        desc = out.get("description") if isinstance(out, dict) else out
        raise RuntimeError(f"telegram API {method} failed: {desc}")
    return out.get("result")


def make_telegram_send_handler(telegram: TelegramConfig) -> Handler:
    """Build a gateway handler bound to one agent's bot + chat allowlist.

    Invoked by the gateway ONLY after all guards pass (never under dry-run). The
    non-allowlisted-chat refusal lives in the handler so it sits on the real execution
    path — not only in the code that happens to build actions today.
    """
    allowed = frozenset(telegram.chat_ids)

    def _handler(action: dict[str, Any]) -> str:
        chat_id = str(action.get("chat_id") or "")
        if chat_id not in allowed:
            raise PermissionError(
                f"telegram_send to chat {chat_id!r} refused: not in the agent's "
                f"allowlisted chat_ids"
            )
        token = resolve_bot_token(telegram)
        payload: dict[str, Any] = {"chat_id": chat_id, "text": str(action.get("text", ""))}
        reply_to = action.get("reply_to_message_id")
        if reply_to:
            payload["reply_parameters"] = {
                "message_id": int(reply_to),
                "allow_sending_without_reply": True,  # original deleted ⇒ still deliver
            }
        result = api_call(token, "sendMessage", payload)
        message_id = result.get("message_id") if isinstance(result, dict) else None
        return f"telegram message {message_id} → chat {chat_id}"

    return _handler


def send_telegram_message(
    text: str,
    *,
    gateway: ActionGateway,
    telegram: TelegramConfig,
    chat_id: str,
    dedup_hint: str,
    reply_to_message_id: int | None = None,
    rationale: str = "",
) -> GatewayResult:
    """Send one message through the gateway. Refuses empty text BEFORE the gateway.

    Long content is truncated under Telegram's 4096-char cap with an explicit marker —
    a silently split/failed report is worse than a visibly shortened one.
    """
    if not text.strip():
        raise ValueError("Refusing to send an empty telegram message.")
    if len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS] + "… [cắt bớt do giới hạn độ dài Telegram]"
    action: dict[str, Any] = {
        "type": "telegram_send",
        "chat_id": str(chat_id),
        "text": text,
        "dedup_hint": dedup_hint,
    }
    if reply_to_message_id is not None:
        action["reply_to_message_id"] = int(reply_to_message_id)
    return gateway.execute(
        action, handler=make_telegram_send_handler(telegram), rationale=rationale
    )
