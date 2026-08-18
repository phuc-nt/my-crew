"""Purpose-named content caps + continuation footer — one home for prompt-bound trims.

Every place that feeds bounded text into a model prompt used to carry its own private
`*_MAX_CHARS` constant; the same MEANING lived under several names (page content 8000
in scrape AND official fetch, merged artifacts 256k in react AND deep loops). This
module names each cap by what it bounds, so a future value change (bench scope — never
change silently) happens in exactly one place.

`cap_with_footer` is the anti-silent-truncation helper: a cut without a marker reads
as "that was everything", and the model concludes from missing data as if it were
complete. The footer states how much was shown and how to get the rest.
"""

from __future__ import annotations

#: One web page (scraped markdown / official-page fetch) fed into a prompt.
PAGE_CONTENT_CHARS = 8000

#: One structured tool result (e.g. Google Workspace JSON) handed back to the loop.
TOOL_RESULT_CHARS = 6000

#: Error text fed back to the model — enough to act on, never a traceback dump.
ERROR_MSG_CHARS = 300

#: Total merged step artifacts (react state-scratch / deep-agent filesystem readback).
MERGED_ARTIFACT_CHARS = 256_000


def cap_with_footer(text: str, cap: int, hint: str) -> str:
    """Trim `text` to `cap` chars; when trimmed, append a footer naming the cut and the
    way to continue (`hint` — e.g. "thu hẹp truy vấn", "scrape URL mục con")."""
    if len(text) <= cap:
        return text
    return f"{text[:cap]}\n(Hiển thị {cap}/{len(text)} ký tự. {hint})"
