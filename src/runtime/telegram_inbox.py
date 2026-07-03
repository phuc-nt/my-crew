"""Telegram ask-agent inbox poll (v6 M13) — mirrors the Slack inbox (M11) semantics.

One poll: fetch pending bot updates, answer messages addressed to the agent through the
SAME `qa_answer.answer_mention` pipeline (Q&A + M12 chat-command, transport-agnostic),
and advance a persisted update-offset. Addressing rule: in a private chat (DM) EVERY
text message is for the agent (there is nobody else); in a group the message must
contain `@<agent-id>` — the same plain-text convention as the Slack inbox.

Watermark discipline (identical to M11): an infrastructure failure (provider/budget/
network) HOLDS the offset so the message is retried; a message-specific failure is
skipped past. Group chatter not addressed to the agent is consumed silently (offset
advances — it must never be re-read). Bootstrap acknowledges any pre-existing backlog
without answering it.

Why this cannot loop on itself (the M11 R1 risk): Telegram's getUpdates NEVER returns
messages sent by bots — neither this bot's own replies nor another bot's messages
(Bot API design: bots cannot see bot output). The self-loop that M11 had to defuse
structurally (sanitize_reply stripping `@<agent-id>`) is impossible on this transport;
sanitize still runs anyway via the shared reply path.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
from pathlib import Path
from typing import Any

from src.llm.fallback_policy import INFRA_ERRORS
from src.profile.loader import LoadedProfile

logger = logging.getLogger(__name__)

_STATE_FILE = "telegram_inbox_state.json"
#: Same per-poll answer cap as the Slack inbox: a message flood costs bounded LLM money.
_MAX_REPLIES_PER_POLL = 3


def _state_path(data_dir: Path) -> Path:
    return Path(data_dir) / _STATE_FILE


def load_offset(data_dir: Path) -> int | None:
    """Next getUpdates offset, or None before the first poll."""
    path = _state_path(data_dir)
    if not path.exists():
        return None
    try:
        return int(json.loads(path.read_text(encoding="utf-8"))["next_offset"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError):
        logger.warning("telegram inbox state unreadable at %s — re-bootstrapping", path)
        return None


def save_offset(data_dir: Path, next_offset: int) -> None:
    path = _state_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")  # atomic: no truncated-JSON re-bootstrap
    tmp.write_text(json.dumps({"next_offset": next_offset}), encoding="utf-8")
    os.replace(tmp, path)


def _is_for_agent(message: dict[str, Any], agent_id: str) -> bool:
    """DM ⇒ always; group ⇒ only when the text contains `@<agent-id>`."""
    if message.get("chat_type") == "private":
        return True
    return f"@{agent_id}".lower() in str(message.get("text") or "").lower()


def run_telegram_inbox(loaded: LoadedProfile, settings: Any) -> dict:
    """One poll for one agent's bot. Returns {"status", "replied", "cost_usd", "delivered"}."""
    telegram = loaded.config.telegram
    if telegram is None:
        raise RuntimeError(f"agent {loaded.profile_id!r} has no telegram: block in profile.yaml")
    data_dir = Path(settings.data_dir)
    offset = load_offset(data_dir)

    from src.tools.telegram_read import fetch_new_messages

    try:
        # Bootstrap fetches with offset=-1: Telegram then returns ONLY the newest pending
        # update, so acking `newest+1` confirms the ENTIRE backlog in one page — a plain
        # unbounded fetch caps at 100 and would leak backlog messages >100 into later
        # polls as "new" (review M2).
        messages, next_offset = fetch_new_messages(
            telegram, offset=offset if offset is not None else -1
        )
    except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
        # Bot API unreachable/failing — not any message's fault. Hold the offset, retry.
        logger.warning("telegram inbox %s: fetch failed (%s) — offset held", loaded.profile_id, exc)
        return {"status": "telegram_unreachable", "replied": 0, "cost_usd": None,
                "delivered": False}

    if offset is None:
        # First poll ever: acknowledge whatever backlog exists (Telegram keeps up to 24h)
        # and answer nothing — a bot switched on at noon must not reply to old messages.
        # No backlog ⇒ offset 0 ("from the earliest future update").
        save_offset(data_dir, next_offset if next_offset is not None else 0)
        logger.info("telegram inbox %s: bootstrapped offset, no backlog answered",
                    loaded.profile_id)
        return {"status": "bootstrapped", "replied": 0, "cost_usd": None, "delivered": False}

    if not messages:
        if next_offset is not None:
            save_offset(data_dir, next_offset)  # ack junk updates (non-text, foreign chats)
        return {"status": "no_mentions", "replied": 0, "cost_usd": None, "delivered": False}

    if settings.write_disabled:
        # Kill switch: answering would burn LLM money only for the gateway to refuse the
        # send. Skip the poll WITHOUT advancing the offset — retry when writes come back.
        logger.warning("telegram inbox %s: AGENT_WRITE_DISABLED — poll skipped, offset held",
                       loaded.profile_id)
        return {"status": "writes_disabled", "replied": 0, "cost_usd": None, "delivered": False}

    from src.actions.action_gateway import ActionGateway
    from src.agent.qa_answer import answer_mention
    from src.packs.registry import PackRegistry

    pack = PackRegistry().load(loaded.domain)
    gateway = ActionGateway(
        settings,
        external_channels=loaded.config.slack_external_channels,
        mcp_allowlist=pack.allowlist or None,
    )
    replied, total_cost, have_cost = 0, 0.0, False
    last_acked: int | None = None
    try:
        for message in messages:
            if replied >= _MAX_REPLIES_PER_POLL:
                break  # the rest are picked up next poll (offset stops before them)
            if not _is_for_agent(message, loaded.profile_id):
                last_acked = message["update_id"]  # group chatter: consume silently
                continue
            try:
                outcome, cost = answer_mention(
                    loaded, settings, mention=message, pack=pack, gateway=gateway
                )
            except INFRA_ERRORS:
                logger.exception(
                    "telegram inbox %s: infrastructure failure at %s — offset held for retry",
                    loaded.profile_id, message["ts"],
                )
                break
            except Exception:  # noqa: BLE001 — message-specific: skip it, keep moving
                logger.exception(
                    "telegram inbox %s: failed to answer %s (skipped)",
                    loaded.profile_id, message["ts"],
                )
                last_acked = message["update_id"]
                continue
            logger.info(
                "telegram inbox %s: reply to %s → %s (%s)",
                loaded.profile_id, message["ts"], outcome.status, outcome.summary,
            )
            replied += 1
            last_acked = message["update_id"]
            if cost is not None:
                total_cost += cost
                have_cost = True
    finally:
        gateway.close()

    if last_acked is not None:
        save_offset(data_dir, last_acked + 1)
    return {
        "status": f"replied_{replied}" if replied else "no_mentions",
        "replied": replied,
        "cost_usd": total_cost if have_cost else None,
        "delivered": replied > 0,
    }
