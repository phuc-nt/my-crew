"""Shared secret detection (single source of truth).

Both the hard-block credential check and the audit-log redaction use these
patterns, so a secret that the gateway can detect is also a secret the audit log
will mask. This closes the gap where a secret in a free-text field was blocked
but then written verbatim into the immutable audit trail.

Detection is conservative (broad regexes, generic high-entropy fallback). A
false positive masks a non-secret in the audit log — harmless. A false negative
leaks a secret — the failure we must avoid. So patterns lean toward over-masking.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "***REDACTED***"

# Vendor-specific credential formats (substring/regex, case-insensitive where apt).
_SECRET_REGEXES: tuple[re.Pattern[str], ...] = (
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{8,}"),            # Slack bot/user/app tokens
    re.compile(r"xoxc-[A-Za-z0-9-]{8,}"),                  # Slack browser token
    re.compile(r"xoxd-[A-Za-z0-9%-]{8,}"),                 # Slack browser cookie
    re.compile(r"sk-or-[A-Za-z0-9-]{8,}"),                 # OpenRouter key
    re.compile(r"sk-[A-Za-z0-9]{20,}"),                    # OpenAI-style key
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),             # GitHub PAT / tokens
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),           # GitHub fine-grained PAT
    re.compile(r"AKIA[0-9A-Z]{16}"),                       # AWS access key id
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),                 # Google API key
    re.compile(r"ya29\.[0-9A-Za-z_-]{20,}"),               # Google OAuth token
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),     # PEM private key
    # JWT (header.payload.signature)
    re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"),
    re.compile(r"glpat-[A-Za-z0-9_-]{20,}"),               # GitLab PAT
    re.compile(r"AC[0-9a-f]{32}"),                         # Twilio-style SID
)

# Key names that mark a value as secret-bearing regardless of its content.
_SECRET_KEY_MARKERS: tuple[str, ...] = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "api-key",
    "cookie",
    "authorization",
    "auth_token",
    "access_key",
    "private_key",
    "client_secret",
    "credential",
)


def find_secret(text: str) -> str | None:
    """Return the matched secret pattern name if `text` contains a credential."""
    for rx in _SECRET_REGEXES:
        if rx.search(text):
            return rx.pattern
    return None


def key_is_secret(key: str) -> bool:
    """True if a dict key name marks its value as a secret to mask/deny."""
    low = key.lower()
    return any(marker in low for marker in _SECRET_KEY_MARKERS)


def contains_secret(value: Any) -> str | None:
    """Walk a nested structure; return a reason if any secret is present.

    Detects both secret-bearing keys (non-empty, non-placeholder value) and
    secret patterns appearing in any string leaf, including free-text fields.
    """
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str) and key_is_secret(k):
                if isinstance(v, str) and v and v != REDACTED:
                    return f"secret-bearing key {k!r}"
                if v not in (None, "", REDACTED) and not isinstance(v, (dict, list, tuple)):
                    return f"secret-bearing key {k!r}"
            found = contains_secret(v)
            if found:
                return found
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            found = contains_secret(item)
            if found:
                return found
        return None
    if isinstance(value, str):
        pattern = find_secret(value)
        if pattern:
            return f"value matches secret pattern {pattern!r}"
    return None


def redact(value: Any) -> Any:
    """Recursively mask secrets: secret-keyed values AND secret patterns in text."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and key_is_secret(k):
                out[k] = REDACTED
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(text: str) -> str:
    """Replace any secret pattern occurrences inside a string with the marker."""
    masked = text
    for rx in _SECRET_REGEXES:
        masked = rx.sub(REDACTED, masked)
    return masked
