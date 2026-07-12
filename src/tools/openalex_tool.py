"""OpenAlex academic search — read-only paper lookup, no API key (v31 P6).

Mirrors the `web_search_tool`/`firecrawl_tool` conventions: stdlib urllib (two REST
params don't warrant an SDK), bounded timeout, and a hard egress hygiene rule — the
QUERY is redacted through the shared secret patterns BEFORE it leaves the machine,
and a query still sensitive after redaction is refused (fail-closed, empty result).

The single fixed host is `api.openalex.org` (no user-supplied URL ⇒ no SSRF surface).
No key is needed; an optional `mailto` (env `OPENALEX_MAILTO`) joins OpenAlex's
"polite pool" for better rate limits.

Results (titles/abstracts) are THIRD-PARTY TEXT: `render_works` wraps every entry
with `format_internal_content` (delimiters + injection-marker quarantine) so the text
reaches an LLM loop only inside the untrusted-content envelope, and the whole render
is bounded.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_API_BASE = "https://api.openalex.org/works"
_TIMEOUT_S = 10
_MAX_PER_PAGE = 10
#: Reconstructed-abstract cap per work; total render cap for the loop.
_ABSTRACT_MAX_CHARS = 700
_RENDER_MAX_CHARS = 4000
_MAX_AUTHORS = 5


@dataclass(frozen=True)
class OpenAlexWork:
    """One normalized work (paper) from the OpenAlex API."""

    id: str
    title: str
    authors: tuple[str, ...]
    year: int | None
    venue: str
    cited_by: int
    doi: str
    abstract: str  # reconstructed from the inverted index, bounded


def search_works(query: str, *, per_page: int = 5, mailto: str | None = None,
                 timeout: float = _TIMEOUT_S) -> list[OpenAlexWork]:
    """Search OpenAlex works by relevance. Returns [] on empty/sensitive query.

    Provider/network failures raise (the caller renders a clear degrade message);
    a sensitive query NEVER egresses — that is a silent-refuse, not an error.
    """
    from src.actions.secret_patterns import query_still_sensitive, redact_query

    query = (query or "").strip()
    if not query:
        return []
    redacted, _counts = redact_query(query)
    if query_still_sensitive(redacted):
        logger.info("openalex: query still sensitive after redaction — egress skipped")
        return []

    params = {
        "search": redacted,
        "per-page": str(max(1, min(int(per_page), _MAX_PER_PAGE))),
    }
    polite = mailto or os.environ.get("OPENALEX_MAILTO", "").strip()
    if polite:
        params["mailto"] = polite
    url = f"{_API_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed https host
        body = json.loads(resp.read().decode("utf-8"))
    results = body.get("results", []) if isinstance(body, dict) else []
    return [parse_work(raw) for raw in results if isinstance(raw, dict)]


def parse_work(raw: dict) -> OpenAlexWork:
    """Map one raw OpenAlex work to the normalized shape (tolerant of absent fields)."""
    authorships = raw.get("authorships") or []
    authors = tuple(
        str(((a.get("author") or {}).get("display_name")) or "?")
        for a in authorships[:_MAX_AUTHORS]
        if isinstance(a, dict)
    )
    source = ((raw.get("primary_location") or {}).get("source") or {})
    return OpenAlexWork(
        id=str(raw.get("id") or ""),
        title=str(raw.get("display_name") or "(không tiêu đề)"),
        authors=authors,
        year=raw.get("publication_year") if isinstance(raw.get("publication_year"), int)
        else None,
        venue=str(source.get("display_name") or ""),
        cited_by=int(raw.get("cited_by_count") or 0),
        doi=str(raw.get("doi") or ""),
        abstract=reconstruct_abstract(raw.get("abstract_inverted_index")),
    )


def reconstruct_abstract(inverted: dict | None) -> str:
    """OpenAlex ships abstracts as {word: [positions]}; rebuild the text, bounded."""
    if not isinstance(inverted, dict) or not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        if isinstance(idxs, list):
            positions.extend((int(i), str(word)) for i in idxs)
    positions.sort()
    text = " ".join(w for _, w in positions)
    if len(text) > _ABSTRACT_MAX_CHARS:
        text = text[:_ABSTRACT_MAX_CHARS] + "…"
    return text


def render_works(works: list[OpenAlexWork]) -> str:
    """Bounded, untrusted-wrapped text of the results for an LLM loop.

    Every work's free-text (title/venue/abstract — third-party content) rides inside
    a `format_internal_content` envelope; the trusted numeric/citation line stays
    outside so the model can cite id/year/citations verbatim.
    """
    from src.tools.search_result_formatter import format_internal_content

    if not works:
        return "(không tìm thấy paper nào)"
    parts: list[str] = []
    for i, w in enumerate(works, start=1):
        meta = (f"[{i}] {w.year or '?'} · trích dẫn: {w.cited_by}"
                + (f" · doi: {w.doi}" if w.doi else "") + f" · {w.id}")
        body = w.title
        if w.authors:
            body += f"\nTác giả: {', '.join(w.authors)}"
        if w.venue:
            body += f"\nNơi đăng: {w.venue}"
        if w.abstract:
            body += f"\nTóm tắt: {w.abstract}"
        wrapped = format_internal_content(body, label=f"openalex kết quả {i}")
        parts.append(f"{meta}\n{wrapped}")
    text = "\n\n".join(parts)
    if len(text) > _RENDER_MAX_CHARS:
        text = text[:_RENDER_MAX_CHARS] + "\n… [cắt bớt]"
    return text
