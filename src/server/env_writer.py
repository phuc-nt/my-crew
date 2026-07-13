"""Atomic .env merge-writer for the Setup Wizard (v7 M17).

The wizard is the ONLY web path that writes secrets to `.env`, so this module is the choke
point for that write. Two safety properties matter most:

1. **Whitelist key-names** (red-team MINOR-2): only keys in `SETUP_WRITABLE_KEYS` (or the
   per-agent telegram-token pattern in M18) may be written. A key like PATH / LD_PRELOAD /
   PYTHONPATH could hijack the process or a spawned subprocess (env-injection → RCE), so an
   unknown key name is REFUSED, never written.

2. **Atomic merge** (red-team R2): existing keys/comments in `.env` are preserved; only the
   given keys are added/updated. Write goes to a temp file + `os.replace` so a crash never
   leaves a half-written `.env`. A `.env.bak` is kept from before each write.

This writes the FILE only. The running process does NOT see the new values until it is
restarted (`load_dotenv` does not override `os.environ`, and the session secret binds once
at app build) — that restart is the wizard's `finish` step, not this module's job.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from src.config.settings import REPO_ROOT

_ENV_PATH = REPO_ROOT / ".env"

#: Keys the Setup Wizard may write. Deliberately EXCLUDES process-behavior keys (DRY_RUN,
#: AGENT_WRITE_DISABLED) and the auth keys (WEB_AUTH_PASSWORD_HASH / WEB_SESSION_SECRET are
#: written only by the `finish` step through the dedicated password path, not free-form env).
SETUP_WRITABLE_KEYS: frozenset[str] = frozenset({
    "OPENROUTER_API_KEY", "OPENROUTER_MODEL",
    "ATLASSIAN_SITE_NAME", "ATLASSIAN_USER_EMAIL", "ATLASSIAN_API_TOKEN",
    "SLACK_XOXC_TOKEN", "SLACK_XOXD_TOKEN", "SLACK_TEAM_DOMAIN",
    "SLACK_REPORT_CHANNEL", "SLACK_STAKEHOLDER_CHANNEL", "SLACK_EXTERNAL_CHANNELS",
    "JIRA_PROJECT_KEY", "GITHUB_REPO",
    "CONFLUENCE_SPACE_KEY", "CONFLUENCE_SPACE_ID", "OKR_CONFLUENCE_PAGE_ID",
    "TAVILY_API_KEY", "BRAVE_API_KEY",
    # v39 #2: SMTP config for email delivery + send_message email channel (Connections UI).
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
    "SMTP_FROM_ADDR", "SMTP_USE_TLS", "SMTP_RECIPIENTS",
    # BIND_HOST/PORT deliberately NOT wizard-writable (review M2): setting BIND_HOST=0.0.0.0
    # before finishing wedges startup via assert_bind_safe. Exposing to LAN is a deliberate
    # post-setup step (edit .env + restart), not a first-run wizard field.
})

#: The auth keys the `finish` step writes (separate allow so free-form env writes can't set
#: them, but the dedicated finish path can).
FINISH_WRITABLE_KEYS: frozenset[str] = frozenset({
    "WEB_AUTH_USERNAME", "WEB_AUTH_PASSWORD_HASH", "WEB_SESSION_SECRET",
})

#: Per-agent telegram bot token (M18): `<AGENT>_TELEGRAM_BOT_TOKEN`, agent id upper-cased.
_TELEGRAM_TOKEN_RE = re.compile(r"^[A-Z0-9_]+_TELEGRAM_BOT_TOKEN$")

_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class DisallowedEnvKey(ValueError):
    """A key name not permitted for this write path (→ 400)."""


def is_writable(key: str, *, allow: frozenset[str], allow_telegram_token: bool = False) -> bool:
    """True when `key` may be written on this path. Never trust a client-supplied key name."""
    if not _KEY_RE.match(key):
        return False
    if key in allow:
        return True
    return allow_telegram_token and bool(_TELEGRAM_TOKEN_RE.match(key))


def merge_env(
    updates: dict[str, str], *, allow: frozenset[str], allow_telegram_token: bool = False,
    env_path: Path | None = None,
) -> None:
    """Merge `updates` into `.env`, atomically, preserving unrelated lines.

    Raises DisallowedEnvKey if any key is not writable on this path (nothing is written —
    all-or-nothing), or if any VALUE carries a control character: a newline in a value
    would append a second `KEY=...` line, smuggling a key past the whitelist entirely
    (e.g. WEB_AUTH_PASSWORD_HASH, which FINISH_WRITABLE_KEYS exists to fence off).
    A blank/None value is skipped (don't overwrite a set key with empty).
    """
    for key, value in updates.items():
        if not is_writable(key, allow=allow, allow_telegram_token=allow_telegram_token):
            raise DisallowedEnvKey(f"env key {key!r} không được phép ghi qua đường này")
        if any(ord(ch) < 0x20 or ch == "\x7f" for ch in str(value)):
            raise DisallowedEnvKey(
                f"giá trị cho {key!r} chứa ký tự điều khiển (xuống dòng?) — từ chối"
            )

    path = env_path or _ENV_PATH
    clean = {k: str(v) for k, v in updates.items() if str(v).strip() != ""}
    if not clean:
        return

    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(clean)
    out: list[str] = []
    for line in existing_lines:
        m = re.match(r"^\s*([A-Z][A-Z0-9_]*)=", line)
        if m and m.group(1) in remaining:
            key = m.group(1)
            out.append(f"{key}={remaining.pop(key)}")  # update in place, keep position
        else:
            out.append(line)
    for key, value in remaining.items():  # brand-new keys appended at end
        out.append(f"{key}={value}")

    import shutil

    if path.exists():
        shutil.copy2(path, Path(str(path) + ".bak"))  # keep a backup, don't move the original
    tmp = Path(str(path) + f".{os.getpid()}.tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # atomic swap in the new content


def read_key_presence(keys: frozenset[str], *, env_path: Path | None = None) -> dict[str, bool]:
    """Return {key: is_set} — WHETHER each key has a non-empty value, never the value itself
    (the wizard status shows 'đã đặt' / 'chưa đặt', never a secret)."""
    path = env_path or _ENV_PATH
    present: dict[str, bool] = {k: False for k in keys}
    if not path.exists():
        return present
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Z][A-Z0-9_]*)=(.*)$", line)
        if m and m.group(1) in present:
            present[m.group(1)] = bool(m.group(2).strip())
    return present
