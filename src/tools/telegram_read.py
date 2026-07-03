"""Telegram READ — getUpdates poll for one agent's bot (v6 M13). Read layer, no gateway.

Fetches pending updates and maps text messages from ALLOWLISTED chats into the same
mention-dict shape the Slack inbox produces, so the answer pipeline (`qa_answer` +
`chat_command`) is transport-agnostic. Updates from any chat NOT in the agent's
`chat_ids` are dropped here — first tier of the two-tier chat allowlist (the send
handler is the second).

Offset semantics (Telegram's native watermark): `getUpdates(offset=N)` returns only
updates with update_id >= N, and marks everything below N as confirmed. The poller
persists `last processed update_id + 1`, which is exactly the M11 watermark pattern —
hold it on infrastructure failure, advance it per processed message.
"""

from __future__ import annotations

import logging
from typing import Any

from src.actions.telegram_write import api_call
from src.config.telegram_config import TelegramConfig
from src.config.telegram_token import resolve_bot_token

logger = logging.getLogger(__name__)


def _to_mention(update: dict[str, Any]) -> dict[str, Any] | None:
    """Map one Telegram update → the transport-agnostic mention dict, or None.

    Only plain text messages count (edits, joins, stickers, photos ⇒ None — the QA
    path answers text). `ts` must be immutable + unique per message because it keys the
    gateway reply dedup: `tg:<chat_id>:<message_id>` is both.
    """
    msg = update.get("message")
    if not isinstance(msg, dict):
        return None
    text = str(msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    if not text or not chat_id:
        return None
    return {
        "ts": f"tg:{chat_id}:{msg.get('message_id')}",
        "text": text,
        "channel": chat_id,
        "user": str((msg.get("from") or {}).get("id") or ""),
        "transport": "telegram",
        "message_id": msg.get("message_id"),
        "chat_type": str(chat.get("type") or ""),
        "update_id": int(update.get("update_id") or 0),
    }


def fetch_new_messages(
    telegram: TelegramConfig, *, offset: int | None
) -> tuple[list[dict[str, Any]], int | None]:
    """(text messages from allowlisted chats, oldest-first; next offset to persist).

    The next offset is `max(update_id) + 1` over ALL fetched updates — including ones
    filtered out (foreign chats, non-text) — because an unacknowledged junk update would
    otherwise be re-fetched forever. Returns (…, None) when nothing was fetched, meaning
    "keep whatever offset you had". Network/API errors propagate to the poller, which
    holds its offset and retries next tick.
    """
    token = resolve_bot_token(telegram)
    payload: dict[str, Any] = {"timeout": 0, "allowed_updates": ["message"]}
    if offset is not None:
        payload["offset"] = offset
    updates = api_call(token, "getUpdates", payload)
    if not isinstance(updates, list) or not updates:
        return [], None
    next_offset = max(int(u.get("update_id") or 0) for u in updates) + 1

    allowed = frozenset(telegram.chat_ids)
    messages = []
    for update in updates:
        mention = _to_mention(update)
        if mention is None:
            continue
        if mention["channel"] not in allowed:
            logger.info(
                "telegram: dropped message from non-allowlisted chat %s", mention["channel"]
            )
            continue
        messages.append(mention)
    messages.sort(key=lambda m: m["update_id"])
    return messages, next_offset
