"""Read-only web search: Tavily primary, Brave fallback (v12 M28b).

Stdlib-only HTTP (`urllib.request`), matching the codebase's established convention
for calling a third-party REST API from a tool/action module (see
`my_crew/actions/telegram_write.py`'s documented "stdlib only, no new dependency, mirrors
email_write" rule) — neither `httpx` nor `requests` is a project dependency, and two
simple JSON-REST calls do not justify adding the `tavily-python` SDK.

Threat model / flow (phase file "Web search" requirement):
    query -> redact_query (Stage-1 regex, my_crew.actions.secret_patterns)
          -> FAIL-CLOSED if `query_still_sensitive` after redaction (no egress at all)
          -> Tavily REST (primary); Brave REST (fallback on Tavily failure)
          -> snippets-only: the provider's own snippet text, NEVER a follow-up GET to
             any result URL (the providers already return a snippet in the search
             response — fetching a result page is a categorically different, and much
             larger, egress surface this tool deliberately does not implement)
          -> audit: redacted query + counts + provider + result_count (raw query is
             NEVER passed to `AuditLog` — only the post-redaction string ever leaves
             this function's local scope in any loggable form)

Missing API key(s) => clean degrade: `is_web_search_available` returns False and
`web_search` returns no results without raising, so a step configured with
`web_search: true` but no key silently falls back to internal-only work (phase file:
"thiếu key -> tool tắt sạch (degrade), KHÔNG crash step").
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from my_crew.actions.secret_patterns import query_still_sensitive, redact_query
from my_crew.audit.audit_log import AuditEntry, AuditLog
from my_crew.tools.search_result_formatter import SearchResult

logger = logging.getLogger(__name__)

_TAVILY_URL = "https://api.tavily.com/search"
_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_TIMEOUT_S = 15
_MAX_RESULTS = 5


@dataclass(frozen=True)
class WebSearchConfig:
    """API keys resolved from `Settings` (env-only, never a profile field)."""

    tavily_api_key: str | None
    brave_api_key: str | None

    def available(self) -> bool:
        return bool(self.tavily_api_key or self.brave_api_key)


def _tavily_search(query: str, api_key: str) -> list[SearchResult]:
    """One Tavily REST call. Raises on any transport/parse failure — the caller
    decides whether to fall back to Brave."""
    payload = json.dumps(
        {"api_key": api_key, "query": query, "max_results": _MAX_RESULTS,
         "include_answer": False}
    ).encode("utf-8")
    req = urllib.request.Request(
        _TAVILY_URL, data=payload, headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    raw_results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(raw_results, list):
        return []
    out: list[SearchResult] = []
    for item in raw_results[:_MAX_RESULTS]:
        if not isinstance(item, dict):
            continue
        out.append(SearchResult(
            title=str(item.get("title", "")),
            snippet=str(item.get("content", "")),  # Tavily's snippet field
            source=str(item.get("url", "")),
        ))
    return out


def _brave_search(query: str, api_key: str) -> list[SearchResult]:
    """One Brave REST call (fallback). Raises on any transport/parse failure."""
    url = f"{_BRAVE_URL}?q={urllib.parse.quote(query)}&count={_MAX_RESULTS}"
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "X-Subscription-Token": api_key},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    web = body.get("web") if isinstance(body, dict) else None
    raw_results = web.get("results") if isinstance(web, dict) else None
    if not isinstance(raw_results, list):
        return []
    out: list[SearchResult] = []
    for item in raw_results[:_MAX_RESULTS]:
        if not isinstance(item, dict):
            continue
        out.append(SearchResult(
            title=str(item.get("title", "")),
            snippet=str(item.get("description", "")),  # Brave's snippet field
            source=str(item.get("url", "")),
        ))
    return out


#: Provider call shape: (query, api_key) -> results. Injectable so tests never touch
#: the network — the default is the real `urllib.request` call.
ProviderFn = Callable[[str, str], list[SearchResult]]


def web_search(
    query: str,
    *,
    config: WebSearchConfig,
    audit_log: AuditLog | None = None,
    tavily_fn: ProviderFn = _tavily_search,
    brave_fn: ProviderFn = _brave_search,
) -> list[SearchResult]:
    """Redact -> fail-closed gate -> Tavily/Brave -> audit. Never raises for a
    provider/network failure or a missing key (both degrade to `[]`); a bad `query`
    type is the only programmer error that still surfaces.

    """
    query = (query or "").strip()
    if not query:
        return []

    redacted, counts = redact_query(query)
    if query_still_sensitive(redacted):
        logger.info("web_search: query still sensitive after redaction, egress skipped")
        _audit(audit_log, redacted="", counts=counts, provider="none", result_count=0,
               verdict="skipped", reason="query still sensitive after redaction")
        return []

    if not config.available():
        logger.info("web_search: no provider API key configured, degrading to no-op")
        return []

    results: list[SearchResult] = []
    provider = "none"
    if config.tavily_api_key:
        try:
            results = tavily_fn(redacted, config.tavily_api_key)
            provider = "tavily"
        except Exception as exc:  # noqa: BLE001 — any Tavily failure falls back to Brave
            logger.warning("web_search: tavily failed, trying brave fallback: %s", exc)
    if not results and config.brave_api_key:
        try:
            results = brave_fn(redacted, config.brave_api_key)
            provider = "brave"
        except Exception as exc:  # noqa: BLE001 — both providers failed: degrade to no results
            logger.warning("web_search: brave fallback also failed: %s", exc)
            provider = "none"

    _audit(audit_log, redacted=redacted, counts=counts, provider=provider,
           result_count=len(results), verdict="allow" if results else "skipped",
           reason="" if results else "no results / provider unavailable")
    return results


def _audit(
    audit_log: AuditLog | None, *, redacted: str, counts: dict[str, int], provider: str,
    result_count: int, verdict: str, reason: str,
) -> None:
    """Record the search via the existing audit path. `redacted` is the ONLY query
    form ever passed here — the raw query never reaches this function's caller-visible
    scope in loggable form (it lives only in `web_search`'s local `query` variable)."""
    if audit_log is None:
        return
    audit_log.record(AuditEntry(
        action_type="web_search", tool=f"web_search:{provider}", verdict=verdict,
        reason=reason,
        params={"redacted_query": redacted, "redaction_counts": counts,
                "result_count": result_count},
    ))
