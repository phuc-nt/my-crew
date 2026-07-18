"""Resolve a Telegram bot token from the profile-declared env NAME (v6 M13).

Shared by the read (getUpdates poll) and write (sendMessage handler) paths so the
"name in profile, value in .env, resolved at call time" rule lives in exactly one place.
"""

from __future__ import annotations

import os

from my_crew.config.telegram_config import TelegramConfig


def resolve_bot_token(telegram: TelegramConfig) -> str:
    """The bot token value, read from os.environ at call time. Fails loud when unset —
    a blank token would make every Bot API call 404 with a confusing message."""
    token = os.environ.get(telegram.bot_token_env, "").strip()
    if not token:
        raise RuntimeError(
            f"Telegram bot token env {telegram.bot_token_env!r} is not set. "
            f"Create the bot via @BotFather and put the token in .env."
        )
    return token
