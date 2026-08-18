"""Fetch the official pages picked out of a search bundle, and format them for a prompt.

The gap this closes: sprint mode's only collector is snippets-only by design, so the
vendor's own page could be cited but never opened, and the figures being asked for
(a price, a tier) usually live one click past the snippet. This module makes that one
click — for URLs `official_page_pick` already vetted, never for a URL a model chose.

Everything here is fail-open. Firecrawl unconfigured, offline, refusing an SSRF target,
or simply returning nothing all collapse to the same outcome: return "" and let the
caller draft from the snippet bundle exactly as it does today. That is not defensive
padding — the deployment this was written on has no Firecrawl running, so the no-op
path is the one that must stay correct.

Fetched markdown is UNTRUSTED external content and goes through `format_search_results`
— the same 4-layer spotlight/quarantine treatment a search snippet gets — rather than
being pasted into the prompt raw. A vendor's own page is not automatically safe; it is
just more likely to contain the number.

That treatment is necessary but NOT sufficient here, which is why `_strip_control_markers`
exists. The spotlight guards the MODEL from injected instructions; it does not guard the
PIPELINE from injected control signals, because the sentinel strings are sprint's own
vocabulary and the formatter has no reason to know them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from my_crew.runtime.content_caps import PAGE_CONTENT_CHARS, cap_with_footer

logger = logging.getLogger(__name__)

#: Hard ceiling on pages fetched per step regardless of entity count.
#:
#: Three, not five, and the binding constraint is the LEASE, not the context. Firecrawl's
#: per-page timeout is 60s and DNS resolution has no timeout at all, so five slow vendor
#: hosts can burn 300s+ inside one graph node — a large fraction of the 600s step lease.
#: Overrun means the watchdog reclaims the step and a SECOND worker runs it: double the
#: LLM spend, and this attempt's writes rejected as stale. A bonus round must not be able
#: to cost the step its lease. `on_beat` narrows the same risk from the other side.
MAX_FETCH_PAGES = 3

#: Control markers that belong to the PIPELINE, never to fetched page text. See
#: `_strip_control_markers`.
_CONTROL_MARKERS = (
    "[LỖI NGUỒN TÌM KIẾM]",
    "[KHÔNG CÓ KẾT QUẢ]",
    "[KHÔNG CÓ KHẢ NĂNG TÌM KIẾM]",
)


def _strip_control_markers(markdown: str) -> str:
    """Neutralise sprint's own control sentinels inside untrusted page text.

    `sprint_runner` reads these markers back OUT of the bundle as control signals: they
    decide whether an entity's gap is re-searchable (`_source_refused`), whether the
    bundle holds any data at all (`_has_results`), whether the revise loop runs, and what
    the CEO-facing THIẾU note claims. The bundle is plain text, so a marker is trusted by
    its appearance alone — nothing records who wrote it.

    That was survivable while every byte of the bundle came from a provider snippet. This
    round appends whole page bodies, so a scraped page carrying one forged line can make
    the pipeline announce that a search failed when it in fact succeeded — measured: the
    targeted-search round is skipped and the note flips from "searched but insufficient"
    to "the search source errored". Lying to the CEO about our own sources is worse than
    the missing figure this round was built to find.

    The formatter's spotlight does not cover this. It quarantines instructions aimed at
    the MODEL; these markers are aimed at the CODE, and `quarantined=0` for text holding
    a full sentinel line (verified). So the strip happens here, at the boundary where
    untrusted bytes enter, rather than by teaching four separate readers to distrust
    their input.
    """
    for marker in _CONTROL_MARKERS:
        markdown = markdown.replace(marker, "[…]")
    return markdown


def _firecrawl_config(settings: Any) -> Any | None:
    """A configured `FirecrawlConfig`, or None when the deployment has no Firecrawl.

    None is the ordinary case on a machine with no Firecrawl container, and it must
    read as "skip the fetch round", never as an error.
    """
    base = getattr(settings, "firecrawl_base_url", None)
    if not base:
        return None
    from my_crew.tools.firecrawl_tool import FirecrawlConfig

    return FirecrawlConfig(
        base_url=base, api_key=getattr(settings, "firecrawl_api_key", None)
    )


def firecrawl_available(settings: Any) -> bool:
    """True when this deployment can actually fetch a page.

    Exposed so the caller can record WHY a round fetched nothing instead of leaving a
    reader to infer it from `bytes: 0`. The no-Firecrawl case is the default deployment,
    not an anomaly.
    """
    config = _firecrawl_config(settings)
    return config is not None and bool(config.available())


def fetch_official_pages(
    settings: Any, urls: list[str], *, on_beat: Callable[[], None] | None = None
) -> str:
    """Scrape `urls` and return one formatted block, or "" if nothing was fetched.

    Each page is independent: one failing (blocked, 404, timeout) drops that page and
    the rest still come back. A total failure returns "" — deliberately NOT a sentinel,
    because unlike a search outage this round is an ENHANCEMENT over the snippet
    bundle. The step already has its snippets, so a failed fetch means "no bonus", not
    "we could not look", and emitting a THIẾU sentinel here would tell the reader data
    was unavailable when the snippet bundle in fact holds it.

    `on_beat` is called before each page so the step's lease keeps renewing across a run
    of slow hosts. Without it this loop is the longest un-heartbeated window in the
    pipeline, which is exactly the condition the lease watchdog reclaims a step for.
    """
    if not urls:
        return ""
    config = _firecrawl_config(settings)
    if config is None or not config.available():
        return ""

    from my_crew.tools.firecrawl_tool import scrape_url
    from my_crew.tools.search_result_formatter import SearchResult, format_search_results

    results: list[SearchResult] = []
    for url in urls[:MAX_FETCH_PAGES]:
        if on_beat is not None:
            try:
                on_beat()
            except Exception:  # noqa: BLE001 — a missed beat must not fail the fetch
                logger.debug("sprint: fetch heartbeat failed", exc_info=True)
        try:
            scraped = scrape_url(url, config)
        except Exception as exc:  # noqa: BLE001 — a fetch must never fail the step
            logger.info("sprint: fetch skipped for %s (%s)", url, exc)
            continue
        markdown = str(getattr(scraped, "markdown", "") or "").strip()
        if not markdown:
            continue
        # Truncate first, then strip: a marker straddling the cut would otherwise leave a
        # partial `[LỖI NGUỒN TÌM` tail, which no reader matches but which is still noise.
        # The consumer is a one-shot drafting step with no tools, so the footer's job is
        # honesty (the page continues past the cut), not a continuation recipe.
        bounded = cap_with_footer(
            markdown, PAGE_CONTENT_CHARS,
            "Trang còn dài hơn phần trích — phần sau KHÔNG có trong ngữ cảnh, "
            "không suy đoán nội dung thiếu.",
        )
        results.append(
            SearchResult(
                title=_strip_control_markers(str(getattr(scraped, "title", "") or url)),
                snippet=_strip_control_markers(bounded),
                source=str(getattr(scraped, "url", "") or url),
            )
        )
    if not results:
        return ""
    text, _count, _quarantined = format_search_results(results)
    if not text:
        return ""
    # Labelled so the drafting model can tell a full page from a snippet and cite it as
    # the official source — the distinction the whole round exists to create.
    return f"NỘI DUNG TRANG CHÍNH THỨC (đọc trực tiếp từ trang của nhà cung cấp):\n{text}"
