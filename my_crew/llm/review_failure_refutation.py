"""A reviewer failure the artifact itself refutes.

Measured twice on the role bench (DigitalOcean upstream, the CLEAN price_increase_email
artifact): the self-check failed a correct draft with "thiếu 'áp dụng từ tháng sau'" while
that exact phrase sat in the text. Such a failure sends the step into a rework round
that can only make the draft worse, and on a sprint it is the difference between
`done` and a stall.

The check is deliberately narrow so it never silences a real finding: a failure is
dropped only when it CLAIMS ABSENCE (an absence marker in the sentence) and QUOTES the
phrase it says is absent, and every quoted phrase is in the artifact verbatim (case-
and whitespace-insensitive). A failure that quotes a phrase to criticise it ("câu 'X'
mơ hồ") has no absence marker and is kept; one that quotes a phrase the artifact
really lacks is kept; one with no quote at all is kept — the code cannot judge those.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_QUOTED = re.compile(r"[\"'“‘«]([^\"'”’»]{4,200})[\"'”’»]")
_ABSENCE_MARKERS = (
    "thiếu", "không có", "không nêu", "không đề cập", "không thấy", "không ghi",
    "không xuất hiện", "không chứa", "bỏ sót", "chưa nêu", "chưa có", "chưa đề cập",
    "vắng", "missing", "absent", "not mention", "omit", "lacks",
)


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def refuted_by_the_artifact(failure: str, artifact: str) -> bool:
    """True when `failure` says a quoted phrase is missing and the artifact has it."""
    low = failure.casefold()
    if not any(marker in low for marker in _ABSENCE_MARKERS):
        return False
    quoted = [_fold(q) for q in _QUOTED.findall(failure)]
    if not quoted:
        return False
    body = _fold(artifact)
    return all(q in body for q in quoted)


def split_refuted_failures(
    failures: Iterable[object], artifact: str,
) -> tuple[list[str], list[str]]:
    """Partition reviewer failures into `(kept, refuted)`; order preserved."""
    kept: list[str] = []
    refuted: list[str] = []
    for item in failures:
        text = str(item)
        (refuted if refuted_by_the_artifact(text, artifact) else kept).append(text)
    return kept, refuted
