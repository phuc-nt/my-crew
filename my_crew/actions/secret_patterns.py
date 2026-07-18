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
    # Telegram bot token (v6 M13 introduces this credential class): numeric bot id +
    # ":" + 35-char secret. Word-bounded so issue keys / timestamps can't false-match.
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
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


# ---- Query redaction (v12 M28b) -------------------------------------------------
#
# A SEPARATE, additive pattern group from `_SECRET_REGEXES` above: those catch
# vendor-credential SHAPES (a Slack token, a PEM key) that must never appear anywhere,
# including free text. This group catches PII/identifier SHAPES that are fine inside
# the product (a ticket id in an internal report) but must never ride on an OUTBOUND
# web-search query to a third-party provider (Tavily/Brave) — a different threat model
# (query egress, not audit-log leakage), hence a distinct table rather than folding
# into `_SECRET_REGEXES` (which would over-redact internal audit text that legitimately
# names a ticket id).
_QUERY_SENSITIVE_GROUPS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # Phone: a run of 7-15 digits, optionally grouped by spaces/dashes/dots/parens,
    # optionally a leading "+". Word-bounded-ish via lookaround so it doesn't eat a
    # trailing digit run that is just part of a longer number/id token.
    ("phone", re.compile(r"(?<![\w])(\+?\d[\d\-.\s()]{6,14}\d)(?![\w])")),
    # Ticket id: PROJECT-123 style (Jira/Linear/GitHub issue references) — a query
    # naming an internal ticket key should not leave the system either. Narrower than
    # `api_token_shaped` below (which also matches its full dash-joined shape once it
    # is >=20 chars) — must run BEFORE it or every ticket id gets mis-bucketed.
    ("ticket_id", re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{1,6}\b")),
    # Cloud-key-shaped: AWS-style 20-char uppercase+digit id. Narrower than
    # `api_token_shaped` below (same charset minus lowercase/`_`/`-`, so every
    # cloud-key-shaped 20-char run also matches the broad pattern) — must run BEFORE
    # it or this bucket is unreachable (every match would be counted as
    # `api_token_shaped` instead, silently discarding the more specific bucket).
    ("cloud_key_shaped", re.compile(r"\b[A-Z0-9]{20}\b")),
    # API-token-shaped: a long (>=20 char) run of base62 + common token punctuation,
    # the generic shape underneath most vendor prefixes already covered above. Runs
    # LAST (broadest pattern) so it only catches what the narrower groups above did
    # not already claim — this is what makes redaction ORDER load-bearing, not just
    # cosmetic bucketing: `subn` mutates the string in place per group, so an earlier
    # narrow match is already replaced with `REDACTED` (which itself no longer matches
    # the broad pattern) by the time this group runs.
    ("api_token_shaped", re.compile(r"\b[A-Za-z0-9_-]{20,}\b")),
)


def redact_query(query: str) -> tuple[str, dict[str, int]]:
    """Stage-1 deterministic redaction for an OUTBOUND web-search query.

    Returns `(redacted_query, counts)` where `counts` maps each sensitive-group name
    to how many matches it replaced (a group absent from `counts` matched zero times).
    Order matters: the broad `api_token_shaped` group runs AFTER the narrower
    `email`/`phone`/`ticket_id` groups so a phone number or ticket id is not first
    swallowed into a generic token match and mis-attributed in the count.

    This function only REDACTS; it does not decide fail-open/fail-closed — the caller
    (`web_search_tool`) re-scans the redacted text and refuses egress if anything still
    matches (defense in depth: redaction is regex-based and can miss a novel shape).
    """
    redacted = query
    counts: dict[str, int] = {}
    for name, rx in _QUERY_SENSITIVE_GROUPS:
        redacted, n = rx.subn(REDACTED, redacted)
        if n:
            counts[name] = n
    return redacted, counts


def query_still_sensitive(text: str) -> bool:
    """True if ANY query-sensitive pattern (or a generic secret pattern) still matches.

    Used by `web_search_tool` as the fail-closed gate AFTER `redact_query`: a genuinely
    clean redaction leaves nothing for either pattern set to match; any residual match
    (a shape the regex redacted imperfectly, e.g. overlapping matches) blocks egress
    entirely rather than sending a partially-masked query.
    """
    if find_secret(text) is not None:
        return True
    return any(rx.search(text) for _, rx in _QUERY_SENSITIVE_GROUPS)
