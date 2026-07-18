"""4-layer defense for untrusted web-search results (v12 M28b), plus `format_internal_content`
(second-order injection defense): the SAME delimiter/scan/spotlight treatment reused for a
team-task step's own `result_text` when it is fed forward as the NEXT step's `handoff_context`
or folded into the cross-step aggregate — a step's output is not automatically trusted just
because it was produced inside this codebase; it may itself echo an injection phrase the step
absorbed from a web-search result or a hostile CEO brief.

Web search results are the ONE piece of content in this codebase that comes from an
arbitrary third party (Tavily/Brave, which return whatever a public web page said) and
is fed back into an LLM call. Prompt injection ("ignore your previous instructions and
instead...") is the live threat, so results pass through four independent layers before
they ever reach `build_team_step_messages`:

  L1 delimiter framing  — every result is wrapped in `===SEARCH_RESULT===`/`===END===`
                          markers so the model's own formatting can't be confused with
                          the surrounding prompt structure.
  L2 marker scan         — a regex scan for common injection phrasing (IGNORE/OVERRIDE/
                          EXECUTE/DISREGARD and inverted-instruction patterns), run over
                          EVERY provider-supplied field (title AND snippet — both are
                          attacker-controllable free text a malicious page can set). A
                          hit QUARANTINES the whole result: BOTH title and snippet are
                          replaced with a neutral placeholder (not just the snippet body)
                          rather than dropping the whole search — one adversarial result
                          must not blind the step to the other, clean results.
  L3 message sandbox     — the CALLER's job (`team_task_prompt.build_team_step_messages`):
                          formatted text from this module rides in its own trailing
                          message, never merged into the system prompt or the step's
                          own instructions.
  L4 spotlighting        — each result is tagged `[EXTERNAL_DATA source=<domain> rank=<n>]`
                          so the model has an explicit, structural cue that this text is
                          reference data, not something to obey. `source` is ALSO
                          attacker-controllable (it is the provider's raw result URL, see
                          `web_search_tool`) — it never rides into the tag as free text:
                          only a validated hostname (scheme/path/query stripped, and
                          itself re-scanned for injection phrasing) is interpolated, so a
                          `source` value crafted as `x] IGNORE ALL PREVIOUS …` can neither
                          forge the L4 tag's structure nor smuggle an instruction through
                          it unscanned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

_DELIM_START = "===SEARCH_RESULT==="
_DELIM_END = "===END==="

#: L2: phrasing that tries to redirect the model's behavior. Case-insensitive,
#: intentionally broad (a false positive just quarantines one snippet — cheap; a false
#: negative lets an injection through — expensive). Covers both English and Vietnamese
#: phrasing (this codebase's CEO-facing surface and prompts are Vietnamese, so an
#: adversarial page targeting it is more likely to use Vietnamese imperatives than
#: English ones — English-only coverage was a real gap, not a deferred nice-to-have).
_INJECTION_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\bignore\s+(all\s+|the\s+)?(previous|prior|above)\s+(instructions?|prompts?|task)\b",
        re.I,
    ),
    re.compile(r"\boverride\s+(your\s+|the\s+)?(instructions?|system|rules?)\b", re.I),
    re.compile(r"\bexecute\s+(the\s+following|this)\s+(command|instruction)\b", re.I),
    re.compile(r"\bdisregard\s+(all\s+|the\s+)?(previous|prior|above)\b", re.I),
    re.compile(r"\byou\s+are\s+now\s+(a|an|in)\b", re.I),  # role-hijack framing
    re.compile(r"\bnew\s+instructions?\s*:", re.I),
    re.compile(r"\bsystem\s*:\s*", re.I),  # fake system-turn injection
    # Vietnamese imperatives: bỏ qua (ignore), ghi đè (override), lờ đi (disregard),
    # thực thi (execute) — each followed by an instruction-referring noun, mirroring the
    # English patterns above rather than bare-word matching (avoids flagging ordinary
    # Vietnamese prose that happens to contain one of these common verbs alone).
    re.compile(r"\bbỏ\s*qua\s+(tất\s*cả\s+|các\s+)?(hướng\s*dẫn|chỉ\s*thị|lệnh|yêu\s*cầu)\b", re.I),
    re.compile(r"\bghi\s*đè\s+(lên\s+)?(hướng\s*dẫn|chỉ\s*thị|hệ\s*thống|quy\s*tắc)\b", re.I),
    re.compile(r"\blờ\s*đi\s+(tất\s*cả\s+|các\s+)?(hướng\s*dẫn|chỉ\s*thị|lệnh)\b", re.I),
    re.compile(r"\bthực\s*thi\s+(lệnh|chỉ\s*thị|hướng\s*dẫn)\s+sau\b", re.I),
)

_QUARANTINE_PLACEHOLDER = "[nội dung bị giữ lại — nghi ngờ chèn lệnh (prompt injection)]"


@dataclass(frozen=True)
class SearchResult:
    """One raw search hit before formatting — the shape `web_search_tool` produces."""

    title: str
    snippet: str
    source: str  # domain / provider-attributed source label, for the L4 spotlight tag


@dataclass(frozen=True)
class FormattedSearchResult:
    """One formatted result: rank, whether L2 quarantined it, and the final text."""

    rank: int
    source: str
    quarantined: bool
    text: str


#: Hostname charset accepted into the L4 tag verbatim — letters, digits, dot, hyphen.
#: Anything else (brackets, whitespace, control chars — the stuff a forged `source`
#: would need to break out of the `[EXTERNAL_DATA ...]` tag or splice in a fake
#: instruction line) falls back to `_UNKNOWN_SOURCE` instead of being interpolated.
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9.-]+$")
_UNKNOWN_SOURCE = "unknown"

#: A `format_internal_content` `label` is natural-language (a step/task title the CEO
#: or a decompose LLM chose — Vietnamese text, not a hostname), so it needs a wider
#: charset than `_HOSTNAME_RE`. Still excludes the specific characters a forged label
#: would need to break out of the `[INTERNAL_STEP_RESULT label=...]` tag: `[`/`]`
#: (closes/reopens the tag early), any newline/control char (splices in a fake new
#: line the model could read as its own instruction), and backslashes (escape-style
#: smuggling). `\w` is Unicode-aware in Python 3 (matches Vietnamese diacritics), so
#: this is deliberately permissive on ALPHANUMERIC content while still closing the
#: same structural gap `_safe_hostname` closes for `source`.
_LABEL_RE = re.compile(r"^[^\[\]\\\x00-\x1f\x7f]+$")
_UNKNOWN_LABEL = "internal"


def scan_for_injection_markers(text: str) -> bool:
    """L2: True if `text` contains a recognizable injection-style phrase."""
    return any(rx.search(text) for rx in _INJECTION_MARKERS)


def _safe_hostname(source: str) -> str:
    """L4: reduce a provider-supplied `source` (often a full result URL) to a validated
    hostname-only string, or `_UNKNOWN_SOURCE` on anything that doesn't cleanly parse.

    `source` is attacker-controllable (Tavily/Brave return whatever a page's own metadata
    claims), so it is NEVER interpolated into the tag as free text — only a hostname that
    passes the charset whitelist AND the same L2 marker scan is used. This defeats both a
    forged tag close (`x] IGNORE ...`) and a clean-looking hostname that still smuggles an
    injection phrase after the whitelist would otherwise let it through unnoticed.
    `urlsplit` itself raises `ValueError` on some malformed input (e.g. unbalanced `[`/`]`,
    which a hostile `source` can trivially contain) — that is also a parse failure, not a
    crash worth propagating.
    """
    if not source:
        return _UNKNOWN_SOURCE
    candidate = source.strip()
    # Bare hostnames (no scheme) still parse via urlsplit if given a `//` prefix; try the
    # raw string first (covers "https://example.com/x"), then a `//`-prefixed retry
    # (covers a bare "example.com" or "example.com/x" with no scheme).
    try:
        hostname = urlsplit(candidate).hostname
        if not hostname:
            hostname = urlsplit(f"//{candidate}").hostname
    except ValueError:
        return _UNKNOWN_SOURCE
    if not hostname:
        return _UNKNOWN_SOURCE
    if not _HOSTNAME_RE.match(hostname):
        return _UNKNOWN_SOURCE
    if scan_for_injection_markers(hostname):
        return _UNKNOWN_SOURCE
    return hostname


def _format_one(result: SearchResult, rank: int) -> FormattedSearchResult:
    quarantined = (
        scan_for_injection_markers(result.title)
        or scan_for_injection_markers(result.snippet)
        or scan_for_injection_markers(result.source)
    )
    body = _QUARANTINE_PLACEHOLDER if quarantined else result.snippet.strip()
    title = _QUARANTINE_PLACEHOLDER if quarantined else result.title.strip()
    safe_source = _safe_hostname(result.source)
    tag = f"[EXTERNAL_DATA source={safe_source} rank={rank}]"
    text = f"{_DELIM_START}\n{tag}\n{title}\n{body}\n{_DELIM_END}"
    return FormattedSearchResult(
        rank=rank, source=result.source, quarantined=quarantined, text=text
    )


def format_search_results(results: list[SearchResult]) -> tuple[str, int, int]:
    """Apply all 4 layers; returns `(formatted_text, result_count, quarantined_count)`.

    `formatted_text` is what the caller places in its OWN trailing message (never the
    system prompt, never concatenated into the step's own instructions — L3 is enforced
    by the caller). Empty `results` ⇒ `("", 0, 0)`.
    """
    if not results:
        return "", 0, 0
    formatted = [_format_one(r, i + 1) for i, r in enumerate(results)]
    text = "\n\n".join(f.text for f in formatted)
    quarantined_count = sum(1 for f in formatted if f.quarantined)
    return text, len(formatted), quarantined_count


def format_internal_content(text: str, *, label: str) -> str:
    """L1/L2/L4 (not L3 — same as `format_search_results`, sandboxing is the caller's
    job) applied to a piece of INTERNAL content that nonetheless carries second-order
    injection risk: a team-task step's own `result_text` — produced by an LLM call that
    may itself have echoed an injection phrase absorbed from web-search results or a
    hostile CEO brief. Reusing the SAME defense a first-order external source gets
    (`format_search_results`) closes that gap: a prior step is not automatically
    "trusted" just because it ran inside this codebase.

    `label` becomes the L4 spotlight tag's identity (e.g. a step title, or "aggregate")
    — free text from the CALLER (a step title/task title the CEO or decompose LLM
    chose), so it gets the SAME two-part guard `_safe_hostname` applies to a search
    result's `source`: a charset whitelist (`_LABEL_RE`, blocking `[`/`]`/newlines/
    control chars — the structural characters a forged label would need to break out
    of the tag) AND the injection-marker scan, either failing falls back to a fixed
    placeholder rather than interpolating the untrusted text. Returns the
    delimited/tagged/quarantined-if-needed text, or `""` unchanged for empty input
    (nothing to wrap).
    """
    text = text.strip()
    if not text:
        return ""
    quarantined = scan_for_injection_markers(text) or scan_for_injection_markers(label)
    body = _QUARANTINE_PLACEHOLDER if quarantined else text
    stripped_label = label.strip()
    if not stripped_label or not _LABEL_RE.match(stripped_label):
        safe_label = _UNKNOWN_LABEL
    elif scan_for_injection_markers(stripped_label):
        safe_label = _QUARANTINE_PLACEHOLDER
    else:
        safe_label = stripped_label
    tag = f"[INTERNAL_STEP_RESULT label={safe_label}]"
    return f"{_DELIM_START}\n{tag}\n{body}\n{_DELIM_END}"
