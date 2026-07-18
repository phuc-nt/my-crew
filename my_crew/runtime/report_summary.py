"""Bounded, plain-text summary of a composed report (v8 M22).

The portfolio roll-up (admin `project-rollup`) needs each agent's most recent report
CONTENT, but the run-event log only carried metadata. This extracts a short, tag-free
prefix of the report text to store on the run event — enough for a one-glance roll-up,
never the whole report.

Text-only extraction (a regex strip of XHTML tags, NOT an HTML parser) so a pathological
tag can't blow the bound or execute anything, and the cut lands on a sentence boundary
when one is near the limit. Internal content — the caller writes it only for internal runs,
and the fleet-status API whitelists run-event fields so this never reaches a client.
"""

from __future__ import annotations

import re

#: Max characters kept for the roll-up. A one-glance digest, not the report.
MAX_SUMMARY_CHARS = 500

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def summarize_report(report_text: str, *, limit: int = MAX_SUMMARY_CHARS) -> str:
    """A bounded, tag-free, whitespace-collapsed prefix of `report_text`.

    Strips XHTML/markdown-ish tags, collapses whitespace, then cuts at `limit` — snapping
    back to the last sentence end (`. ! ? …`) within the tail if one is reasonably close,
    else hard-cutting with an ellipsis. Empty/blank input ⇒ "" (the roll-up shows "chưa có
    báo cáo")."""
    if not report_text or not report_text.strip():
        return ""
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", report_text)).strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    # Prefer a sentence boundary in the last quarter of the window over a mid-word cut.
    window = head[int(limit * 0.75):]
    cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "), window.rfind("… "))
    if cut != -1:
        return head[: int(limit * 0.75) + cut + 1].strip()
    return head.rstrip() + "…"
