"""Ask-agent Slack inbox poll (v3 M11). Generic — no domain knowledge.

The scheduler fires kind `inbox` every `poll_minutes` (profile `inbox:` block). One
poll: search the configured channel for NEW messages containing `@<agent-id>` (plain
text — browser-token Slack has no bot user to @-mention), answer each through
`qa_answer.answer_mention`, and advance a persisted ts watermark.

Why this cannot loop on itself (risk R1): replies are posted IN THREAD and never
contain the `@<agent-id>` phrase, so the search never matches the agent's own output;
the gateway dedup (keyed on the mention's immutable ts) additionally makes every
mention answerable at most once, across restarts.

Bootstrap: the first poll ever answers NOTHING — it just records the newest existing
ts as the watermark. An agent switched on at noon must not reply to a month of
backlog mentions.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.adapters.mcp_adapter import call_tool
from src.llm.fallback_policy import INFRA_ERRORS
from src.profile.loader import LoadedProfile

logger = logging.getLogger(__name__)

_STATE_FILE = "inbox_state.json"
#: Per-poll answer cap: a mention flood costs bounded LLM money; the rest are picked
#: up next poll (watermark only advances over processed messages).
_MAX_REPLIES_PER_POLL = 3
_SEARCH_COUNT = 20


def _state_path(data_dir: Path) -> Path:
    return Path(data_dir) / _STATE_FILE


def load_watermark(data_dir: Path) -> str | None:
    """Last processed Slack ts, or None before the first poll."""
    path = _state_path(data_dir)
    if not path.exists():
        return None
    try:
        return str(json.loads(path.read_text(encoding="utf-8"))["last_ts"])
    except (json.JSONDecodeError, KeyError, TypeError, OSError):
        logger.warning("inbox state unreadable at %s — re-bootstrapping", path)
        return None


def save_watermark(data_dir: Path, last_ts: str) -> None:
    path = _state_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")  # atomic: no truncated-JSON re-bootstrap
    tmp.write_text(json.dumps({"last_ts": last_ts}), encoding="utf-8")
    os.replace(tmp, path)


def _find_channel(out: Any, channel_id: str) -> str | None:
    for ch in out.get("channels", []) if isinstance(out, dict) else []:
        if ch.get("id") == channel_id:
            return str(ch["name"])
    return None


def _channel_name(slack_server: Any, channel_id: str) -> str:
    """Resolve a channel ID to its name (search's `in:` operator needs the name).

    P1 added a 15-min cache to `list_workspace_channels`, so a newly-created or
    renamed channel can be briefly invisible on the first (possibly cached) lookup.
    Retry ONCE with `bypass_cache: True` before declaring the channel not found —
    only a genuinely absent channel (not a member, wrong id) should still raise.
    """
    out = call_tool(slack_server, "list_workspace_channels", {"include_private": True})
    name = _find_channel(out, channel_id)
    if name is not None:
        return name

    out = call_tool(
        slack_server, "list_workspace_channels",
        {"include_private": True, "bypass_cache": True},
    )
    name = _find_channel(out, channel_id)
    if name is not None:
        return name

    raise RuntimeError(
        f"inbox channel {channel_id!r} not found in the Slack workspace "
        "(is the agent's account a member of it?)"
    )


def fetch_new_mentions(
    slack_server: Any, *, channel_id: str, agent_id: str, last_ts: str | None
) -> tuple[list[dict], str | None]:
    """(new mentions oldest-first, newest ts seen). `last_ts=None` ⇒ bootstrap scan.

    A mention = a message whose text contains `@<agent-id>`. Replies the agent posts
    never contain that phrase, so they can never match (see module docstring).
    """
    name = _channel_name(slack_server, channel_id)
    query = f'in:{name} "@{agent_id}"'
    if last_ts is not None:
        # Bound the result set to the watermark's neighborhood: search returns top-N by
        # the server's own ranking, so an UNBOUNDED query over a channel with years of
        # answered mentions could push a NEW mention out of the page — the inbox would
        # go deaf. `after:` keeps the page recent (1-day overlap absorbs tz/rounding).
        since = datetime.fromtimestamp(float(last_ts)) - timedelta(days=1)
        query += f" after:{since:%Y-%m-%d}"
    out = call_tool(slack_server, "search_messages", {"query": query, "count": _SEARCH_COUNT})
    messages = out.get("messages", []) if isinstance(out, dict) else []
    newest = max((str(m.get("ts") or "") for m in messages), default=None)
    if last_ts is None:
        return [], newest
    phrase = f"@{agent_id}".lower()
    fresh = [
        m for m in messages
        if str(m.get("ts") or "") > last_ts and phrase in str(m.get("text") or "").lower()
    ]
    fresh.sort(key=lambda m: str(m.get("ts")))
    return fresh, newest


def run_inbox(loaded: LoadedProfile, settings: Any) -> dict:
    """One poll for one agent: fetch new mentions, answer up to the cap, advance state.

    Returns {"status", "replied", "cost_usd", "delivered"} for the worker's run event.
    A message-specific failure is logged and SKIPPED (watermark advances past it — one
    poison message must not wedge the inbox); an INFRASTRUCTURE failure (provider/
    budget/network, `INFRA_ERRORS`) stops the poll and HOLDS the watermark so the
    question is retried. Note: under `dry_run` a mention IS consumed (reply logged, not
    posted) — dry-run means "show what would happen", and it did.
    """
    if not loaded.inbox:
        raise RuntimeError(f"agent {loaded.profile_id!r} has no inbox: block in profile.yaml")
    channel = loaded.inbox["channel"]
    data_dir = Path(settings.data_dir)

    last_ts = load_watermark(data_dir)
    mentions, newest = fetch_new_mentions(
        loaded.config.slack_server,
        channel_id=channel,
        agent_id=loaded.profile_id,
        last_ts=last_ts,
    )
    if last_ts is None:
        # First poll ever: set the watermark at the newest existing message (or "now"
        # when the channel has no mentions yet) and answer nothing.
        save_watermark(data_dir, newest or f"{time.time():.6f}")
        logger.info("inbox %s: bootstrapped watermark, no backlog answered", loaded.profile_id)
        return {"status": "bootstrapped", "replied": 0, "cost_usd": None, "delivered": False}

    if settings.write_disabled:
        # Kill switch: answering would burn LLM money only for the gateway to refuse the
        # post. Skip the whole poll WITHOUT advancing the watermark — questions asked
        # during the outage are answered when writes come back.
        logger.warning("inbox %s: AGENT_WRITE_DISABLED — poll skipped, watermark held",
                       loaded.profile_id)
        return {"status": "writes_disabled", "replied": 0, "cost_usd": None,
                "delivered": False}

    from src.actions.action_gateway import ActionGateway
    from src.agent.qa_answer import answer_mention
    from src.packs.registry import PackRegistry

    pack = PackRegistry().load(loaded.domain)
    gateway = ActionGateway(
        settings,
        external_channels=loaded.config.slack_external_channels,
        mcp_allowlist=pack.allowlist or None,
        actor=getattr(loaded, "profile_id", ""),  # v46
        auto_approve=getattr(loaded, "auto_approve", None),  # v8 M23: chat-command auto-approve
    )
    replied, total_cost = 0, 0.0
    have_cost = False
    last_processed: str | None = None
    try:
        for mention in mentions[:_MAX_REPLIES_PER_POLL]:
            try:
                outcome, cost = answer_mention(
                    loaded, settings, mention=mention, pack=pack, gateway=gateway
                )
            except INFRA_ERRORS:
                # Provider/budget/network down — NOT this message's fault. Stop the poll
                # and hold the watermark so the question is retried next poll.
                logger.exception(
                    "inbox %s: infrastructure failure at ts=%s — watermark held for retry",
                    loaded.profile_id, mention.get("ts"),
                )
                break
            except Exception:  # noqa: BLE001 — message-specific: skip it, keep moving
                logger.exception(
                    "inbox %s: failed to answer mention ts=%s (skipped)",
                    loaded.profile_id, mention.get("ts"),
                )
                last_processed = str(mention["ts"])
                continue
            logger.info(
                "inbox %s: reply to ts=%s → %s (%s)",
                loaded.profile_id, mention.get("ts"), outcome.status, outcome.summary,
            )
            replied += 1
            last_processed = str(mention["ts"])
            if cost is not None:
                total_cost += cost
                have_cost = True
    finally:
        gateway.close()

    if last_processed is not None:
        save_watermark(data_dir, last_processed)
    return {
        "status": f"replied_{replied}" if mentions else "no_mentions",
        "replied": replied,
        "cost_usd": total_cost if have_cost else None,
        "delivered": replied > 0,
    }
