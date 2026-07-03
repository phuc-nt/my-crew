"""Channel/integration builders (M3-P11) — extra MCP servers + SMTP email config.

Split out of `config_builders_reporting.py` to keep that file under the 200-LOC gate
(mirrors how reporting builders were split out of `config_builders`). Holds the
config-driven extra-server registry (C3) and the SMTP delivery config (D2). Both resolve
env VALUES from os.environ by declared NAMES — secrets never come from a committed profile.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.config.config_builders_helpers import _d_bool, _d_int
from src.config.reporting_config import McpServerSpec
from src.config.smtp_config import SmtpConfig
from src.config.telegram_config import TelegramConfig


def build_extra_servers(d: dict[str, Any]) -> dict[str, McpServerSpec]:
    """Build config-driven extra MCP server specs (C3), keyed by lowercase name.

    Input `d["extra_servers"]` is a list of {name, mcp_dist, required_env} dicts. Env
    VALUES are pulled from os.environ by the declared key NAMES — names live in the
    profile, secrets never do. `validate()` stays lazy (fires only on real use), so a
    declared-but-unused server never breaks load. {} when none declared (backward-compat).
    """
    raw = d.get("extra_servers") or []
    out: dict[str, McpServerSpec] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip().lower()
        if not name:
            continue
        required_env = tuple(str(k) for k in (entry.get("required_env") or ()))
        out[name] = McpServerSpec(
            name=name,
            dist_path=Path(str(entry.get("mcp_dist") or "")),
            env={k: os.environ.get(k, "") for k in required_env},
            required_env_keys=required_env,
        )
    return out


def extra_servers_from_env() -> list[dict[str, Any]]:
    """Env path for extra MCP servers: declare Linear when `LINEAR_MCP_DIST` is set.

    Mirrors the profile `integrations:` shape so `build_extra_servers` consumes it
    identically. Unset ⇒ [] ⇒ no extra server (backward-compat).
    """
    linear_dist = os.getenv("LINEAR_MCP_DIST")
    if not linear_dist:
        return []
    return [{"name": "linear", "mcp_dist": linear_dist, "required_env": ["LINEAR_API_TOKEN"]}]


def build_smtp(d: dict[str, Any]) -> SmtpConfig | None:
    """Build the SMTP delivery config (D2), or None when no email channel declared.

    A `smtp` sub-dict with a host is required; absent ⇒ None ⇒ Slack+Confluence only
    (backward-compat). Fails loud when a host is set but no recipient is given (a silent
    drop otherwise). The password is NEVER read here — resolved from os.environ at send time.
    """
    smtp = d.get("smtp")
    if not isinstance(smtp, dict) or not smtp.get("host"):
        return None
    recipients = smtp.get("recipients") or ()
    if isinstance(recipients, str):
        recipients = tuple(r.strip() for r in recipients.split(",") if r.strip())
    else:
        recipients = tuple(str(r).strip() for r in recipients if str(r).strip())
    if not recipients:
        raise RuntimeError(
            "smtp.host is set but smtp.recipients is empty; an email channel needs at least "
            "one recipient (set smtp.recipients or SMTP_RECIPIENTS), else remove the smtp block."
        )
    return SmtpConfig(
        smtp_host=str(smtp.get("host")),
        smtp_user=str(smtp.get("user") or ""),
        from_addr=str(smtp.get("from_addr") or smtp.get("user") or ""),
        smtp_port=_d_int(smtp, "port", 587),
        use_tls=_d_bool(smtp, "use_tls", True),
        recipients=recipients,
    )


def build_telegram(d: dict[str, Any]) -> TelegramConfig | None:
    """Build the per-agent Telegram bot config (v6 M13), or None when not declared.

    A `telegram` sub-dict with a `bot_token_env` is required; absent ⇒ None ⇒ no telegram
    channel (backward-compat, byte-identical pre-M13). Fails loud when the block exists
    but `chat_ids` is empty: a bot with no allowlisted chat can neither read nor send —
    a silently deaf-and-mute agent is a config error, not a feature. The token VALUE is
    never read here — resolved from os.environ at call time by the transport.
    """
    tg = d.get("telegram")
    if not isinstance(tg, dict) or not tg.get("bot_token_env"):
        return None
    raw_ids = tg.get("chat_ids") or ()
    if isinstance(raw_ids, str):
        chat_ids = tuple(c.strip() for c in raw_ids.split(",") if c.strip())
    else:
        chat_ids = tuple(str(c).strip() for c in raw_ids if str(c).strip())
    if not chat_ids:
        raise RuntimeError(
            "telegram.bot_token_env is set but telegram.chat_ids is empty; the bot needs at "
            "least one allowlisted chat id (DM or group), else remove the telegram block."
        )
    poll = _d_int(tg, "poll_minutes", 5)
    if poll < 1:
        raise RuntimeError("telegram.poll_minutes must be an integer >= 1.")
    return TelegramConfig(
        bot_token_env=str(tg.get("bot_token_env")).strip(),
        chat_ids=chat_ids,
        poll_minutes=poll,
    )


def smtp_from_env() -> dict[str, Any] | None:
    """Env path for the email channel: declare SMTP when `SMTP_HOST` is set.

    Mirrors the profile `smtp:` shape so `build_smtp` consumes it identically. The password
    is NOT read here (resolved at send time from `SMTP_PASSWORD`). Unset host ⇒ None ⇒ no
    email channel (backward-compat).
    """
    host = os.getenv("SMTP_HOST")
    if not host:
        return None
    return {
        "host": host,
        "port": os.getenv("SMTP_PORT"),
        "user": os.getenv("SMTP_USER"),
        "from_addr": os.getenv("SMTP_FROM_ADDR"),
        "use_tls": os.getenv("SMTP_USE_TLS"),
        "recipients": os.getenv("SMTP_RECIPIENTS"),
    }
