"""Skill selection + render for the report compose prompt (v2 M3-P10 Slice 2).

An injectable `SkillSelector` picks which of an agent's candidate skills are relevant to
a report kind; the chosen bodies render into a `<pm_skills>` block injected into the
INTERNAL compose prompt only (external takes nothing — the P5 red line). The selector is
a Callable so tests run offline with a FAKE returning a fixed pick (mirrors the P8
`MemoryExtractor` pattern); the default LLM impl tolerates failure → [] (no skills).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from my_crew.llm.client import LlmClient
    from my_crew.profile.context import ProfileContext
    from my_crew.skills.models import Skill

logger = logging.getLogger(__name__)

# (candidate skills, kind_context) -> chosen skill NAMES.
SkillSelector = Callable[[list["Skill"], str], list[str]]

_SYSTEM = (
    "Bạn chọn các kỹ năng PM phù hợp để soạn một báo cáo. Dưới đây là danh sách kỹ năng "
    "(tên + mô tả). Trả về CHỈ tên các kỹ năng phù hợp với loại báo cáo được hỏi, mỗi tên "
    "một dòng. Không giải thích. Nếu không có cái nào phù hợp, trả về dòng trống."
)


def make_llm_selector(client: LlmClient) -> SkillSelector:
    """Default selector: ask the LLM which skills suit the kind. Failure → [] (graceful)."""

    def _select(candidates: list[Skill], kind_context: str) -> list[str]:
        if not candidates:
            return []
        try:
            listing = "\n".join(f"- {s.name}: {s.description}" for s in candidates)
            result = client.complete(
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user",
                     "content": f"Loại báo cáo: {kind_context}\nKỹ năng:\n{listing}"},
                ]
            )
            return _parse_names(result.content)
        except Exception as exc:  # noqa: BLE001 — skill selection is best-effort, never break a run
            logger.warning("skill selection skipped (LLM unavailable): %s", exc)
            return []

    return _select


def select_skill_text(context: ProfileContext, audience: str, *, kind: str) -> str:
    """Run the selector (internal only) and render the chosen skill bodies, or "".

    External audience, no candidate skills, or no selector ⇒ "" (no injection). The
    selector's returned names are FILTERED to the candidate pool, so a hallucinated name
    is dropped. When the context carries an `agent_id`, the chosen names are recorded for
    the skill curator (v38 #2) — best-effort telemetry that never affects the text.
    """
    if audience != "internal" or not context.skills or context.skill_selector is None:
        return ""
    chosen_names = set(context.skill_selector(list(context.skills), kind))
    chosen = [s for s in context.skills if s.name in chosen_names]
    agent_id = getattr(context, "agent_id", None)
    if agent_id and chosen:
        from my_crew.skills.skill_curator import record_usage

        record_usage(agent_id, [s.name for s in chosen])
    return render_skills(chosen)


def render_skills(skills: list[Skill]) -> str:
    """Wrap the chosen skill bodies in a `<pm_skills>` block ("" when none)."""
    if not skills:
        return ""
    bodies = "\n\n".join(s.body for s in skills)
    return f"<pm_skills>\n{bodies}\n</pm_skills>"


def _parse_names(content: str) -> list[str]:
    """Split the LLM reply into clean skill names (strip bullets/blanks/commas)."""
    names: list[str] = []
    for line in content.replace(",", "\n").splitlines():
        cleaned = line.strip().lstrip("-•* ").strip()
        if cleaned:
            names.append(cleaned)
    return names
