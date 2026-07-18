"""Sibling-fact selection + render for the report compose prompt (v2 M3-P9 A3 Slice 2).

An injectable `SiblingFactSelector` ranks a sibling agent's remembered facts down to the
subset relevant to a report kind; the kept facts render into a labeled block injected into
the INTERNAL compose prompt only (external takes nothing — the P5 red line). The selector
is a Callable so tests run offline with a FAKE returning a fixed subset (mirrors the M3-P10
`SkillSelector`); the default LLM impl tolerates failure → [] (drop all siblings — never
degrade nor flood a report).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from my_crew.llm.client import LlmClient
    from my_crew.profile.context import ProfileContext

logger = logging.getLogger(__name__)

# (sibling facts, kind_context) -> kept facts (a SUBSET of the input, ranked for relevance).
SiblingFactSelector = Callable[[list[str], str], list[str]]

_SYSTEM = (
    "Bạn lọc các ghi chú (fact) từ một agent PM KHÁC cùng dự án, giữ lại CHỈ những fact "
    "liên quan tới loại báo cáo đang soạn. Trả về nguyên văn từng fact được giữ, mỗi fact "
    "một dòng. Không thêm, không sửa, không giải thích. Nếu không có fact nào liên quan, "
    "trả về dòng trống."
)


def make_llm_selector(client: LlmClient) -> SiblingFactSelector:
    """Default selector: ask the LLM which sibling facts suit the kind. Failure → [] (drop)."""

    def _select(facts: list[str], kind_context: str) -> list[str]:
        if not facts:
            return []
        try:
            listing = "\n".join(facts)
            result = client.complete(
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user",
                     "content": f"Loại báo cáo: {kind_context}\nCác fact:\n{listing}"},
                ]
            )
            kept = set(_parse_lines(result.content))
            # Keep only facts that were actually in the input (drop any the LLM invented),
            # preserving input order — same hallucination guard as the skill selector.
            return [f for f in facts if f in kept]
        except Exception as exc:  # noqa: BLE001 — sibling ranking is best-effort, never break a run
            logger.warning("sibling-fact selection skipped (LLM unavailable): %s", exc)
            return []

    return _select


def select_sibling_text(
    context: ProfileContext, audience: str, *, kind: str, project_group: str | None
) -> str:
    """Run the selector (internal only) and render the kept sibling facts, or "".

    External audience, no sibling facts, or no selector ⇒ "" (no injection — the red line).
    """
    if audience != "internal" or not context.sibling_facts or context.sibling_selector is None:
        return ""
    kept = context.sibling_selector(list(context.sibling_facts), kind)
    kept_set = set(kept)
    ordered = [f for f in context.sibling_facts if f in kept_set]  # input order, filtered to pool
    return render_sibling_facts(ordered, project_group)


def render_sibling_facts(facts: list[str], project_group: str | None) -> str:
    """Wrap the kept sibling facts in a labeled block ("" when none)."""
    if not facts:
        return ""
    label = f"--- Bộ nhớ agent khác (project: {project_group}) ---"
    return label + "\n" + "\n".join(facts)


def _parse_lines(content: str) -> list[str]:
    """Split the LLM reply into clean fact lines (strip bullets/blanks)."""
    out: list[str] = []
    for line in content.splitlines():
        cleaned = line.strip().lstrip("-•* ").strip()
        if cleaned:
            out.append(cleaned)
    return out
