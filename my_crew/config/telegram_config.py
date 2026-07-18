"""Telegram identity/channel config (v6 M13) — one bot PER AGENT.

Each agent gets its own Telegram bot (created via BotFather: own name + avatar), so the
agent has a real, separate identity — unlike the shared browser-token Slack account. The
profile stores only the env var NAME holding the bot token; the token value lives in
`.env` and is read at call time (never on an action dict, never in git).

`chat_ids` is the hard allowlist of conversations this agent may participate in — it is
enforced on BOTH directions: the inbox poller ignores updates from any other chat, and
the send handler refuses any other destination (see `telegram_write`). A bot dragged
into a stranger's group can therefore neither read nor speak there.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramConfig:
    """One agent's Telegram bot binding. Presence ⇒ the telegram channel is ON."""

    bot_token_env: str  # env var NAME holding the BotFather token (value in .env only)
    chat_ids: tuple[str, ...]  # allowlisted chat IDs (DM and/or group) — never empty
    poll_minutes: int = 5  # inbox poll cadence (folded into the `inbox` pseudo-kind)
    # v6 M14: the Telegram user id allowed to issue CEO chat-ops commands to this agent
    # (only meaningful on an admin-domain agent). Empty ⇒ no operator ⇒ this agent takes
    # no ops commands, only Q&A. A message from any other user is Q&A/refusal, never ops.
    ops_operator_id: str = ""
