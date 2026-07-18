"""Slack short → Confluence link line (single source, v2 M2-P6 Slice 4).

The "detail link" trailing line was duplicated across the 4 short builders. Factored
here so it has ONE definition, and so a short built URL-free at compose time can have
its real link injected at deliver time (after the Confluence page is created) — the
resume-safe path: the short is checkpointed without a URL, the link is swapped in later.

The no-URL fallback line is byte-identical to what every builder used before, so
extracting it changes no output.
"""

from __future__ import annotations

NO_LINK_LINE = "\n_(không tạo được link Confluence)_"


def slack_link_line(detail_url: str | None, *, text: str) -> str:
    """Trailing link line: a Slack mrkdwn link when there is a URL, else the fallback."""
    if detail_url:
        return f"\n📄 <{detail_url}|{text}>"
    return NO_LINK_LINE


def inject_link(short_no_url: str, detail_url: str | None, *, text: str) -> str:
    """Swap a URL-free short's trailing fallback line for the real link line.

    `short_no_url` was built with `detail_url=None`, so it ALWAYS ends in
    `NO_LINK_LINE`. With no URL, return it unchanged (already the no-link form); with
    a URL, replace exactly that trailing line — no parsing of the body.
    """
    if not detail_url:
        return short_no_url
    return short_no_url.removesuffix(NO_LINK_LINE) + slack_link_line(detail_url, text=text)
