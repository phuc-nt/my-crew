"""Deterministic pre-check for a team step's output — code before the LLM grader.

The sprint lane already refuses to let an LLM be the only judge of coverage
(`sprint_runner.coverage_gaps` is code); the team lane graded purely by LLM. This
module gives team steps the same split: the machine-checkable part of a step's
acceptance — named entities that must appear, an explicit minimum item count — is
measured by code FIRST. A clear miss goes straight back through the existing
recover→work loop without spending a checker call; a clean pass becomes a FACT line
in the checker prompt so the grader starts from what code already proved instead of
re-deriving (or hallucinating) it.

Everything here is fail-open: acceptance text this code cannot confidently parse
contributes nothing, and any internal error means "no gaps found" — the LLM checker
then behaves exactly as before. A false negative costs nothing (the checker still
grades); a false positive costs one cheap recover round, never the task.

Imports `listed_entities` from `sprint_runner` rather than copying it — the entity
grammar (parenthesised subjects beat colon attributes, etc.) was hardened by real
incidents and must not fork. The sprint runner itself is NOT modified.
"""

from __future__ import annotations

import logging
import re

from my_crew.runtime.sprint_runner import listed_entities

logger = logging.getLogger(__name__)


def entity_coverage(criteria: str, artifact: str) -> list[str]:
    """Entities enumerated in `criteria` that `artifact` never mentions.

    Matching is deliberately loose — case-insensitive substring, same as the
    sprint's `coverage_gaps` — because the cost of a wrong "missing" verdict is
    one recover round, while a strict matcher would miss aliases constantly.
    No enumeration in the criteria ⇒ no entities ⇒ no gaps (fail-open).
    """
    text = (artifact or "").lower()
    gaps: list[str] = []
    for entity in listed_entities(criteria or ""):
        name = entity.strip()
        if name and name.lower() not in text:
            gaps.append(name)
    return gaps


#: An explicit quantity demand in acceptance prose — "liệt kê 5 xu hướng",
#: "ít nhất 3 ví dụ", "tối thiểu 2 nguồn", "đủ 4 mục". Only these lead-ins count:
#: a bare number ("bảng 2 cột", "quý 3") is NOT a quantity contract.
_MIN_ITEMS_RE = re.compile(
    r"(?:liệt kê|ít nhất|tối thiểu|đủ)\s+(\d{1,2})\b", re.IGNORECASE
)

#: A list-shaped line in the artifact: bullet or numbered. Used only to COUNT
#: delivered items against an explicit demand.
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*•]|\d{1,3}[.)])\s+\S", re.MULTILINE)


def _required_min_items(criteria: str) -> int:
    """The largest explicit item-count demand in the criteria, or 0."""
    counts = [int(m.group(1)) for m in _MIN_ITEMS_RE.finditer(criteria or "")]
    return max(counts, default=0)


def machine_checkable_gaps(acceptance: str, artifact: str) -> list[str]:
    """The machine-checkable failures of `artifact` against `acceptance`, as
    human-readable gap lines (Vietnamese — they land in `self_check_failures`,
    which the rework prompt and the CEO both read). Empty ⇒ code found nothing
    wrong, which is NOT a pass — it only means the LLM checker takes over.

    Two cheap checks this round, nothing free-form:
    - entity coverage: every entity the acceptance enumerates must be mentioned;
    - minimum item count: an explicit "liệt kê 5 ..."-style demand must be met by
      at least that many list-shaped lines — checked only when the artifact
      actually uses list form (a prose answer is not countable ⇒ fail-open).
    """
    try:
        gaps: list[str] = []
        for name in entity_coverage(acceptance, artifact):
            gaps.append(f"kết quả không nhắc đến {name!r} dù tiêu chí nêu đích danh")
        need = _required_min_items(acceptance)
        if need >= 2:
            have = len(_LIST_ITEM_RE.findall(artifact or ""))
            if 0 < have < need:
                gaps.append(
                    f"tiêu chí đòi ít nhất {need} mục nhưng kết quả chỉ có {have} "
                    "mục dạng danh sách"
                )
        return gaps
    except Exception as exc:  # noqa: BLE001 — a broken pre-check must never fail a step
        logger.warning("deterministic step check failed, skipping: %s", exc)
        return []


def checked_facts_line(acceptance: str, artifact: str) -> str:
    """One FACT line for the checker prompt when code verified something real,
    else "". Only states what was actually measured — a criteria set with no
    machine-checkable part yields "" and the checker prompt stays byte-identical
    to the pre-check era.
    """
    try:
        facts: list[str] = []
        entities = [e for e in listed_entities(acceptance or "") if e.strip()]
        if entities and not entity_coverage(acceptance, artifact):
            facts.append(
                f"đủ {len(entities)}/{len(entities)} thực thể nêu trong tiêu chí "
                "đều được nhắc trong kết quả"
            )
        need = _required_min_items(acceptance)
        if need >= 2:
            have = len(_LIST_ITEM_RE.findall(artifact or ""))
            if have >= need:
                facts.append(f"kết quả có {have} mục dạng danh sách (tiêu chí đòi {need})")
        if not facts:
            return ""
        return "CODE ĐÃ KIỂM (dữ kiện đo bằng máy, không phải nhận định): " + "; ".join(facts) + "."
    except Exception as exc:  # noqa: BLE001 — same fail-open contract as the gaps check
        logger.warning("deterministic facts line failed, skipping: %s", exc)
        return ""
