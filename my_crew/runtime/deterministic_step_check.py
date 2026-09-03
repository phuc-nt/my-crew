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
grades). A false POSITIVE is no longer cheap: rework is capped at one round, so a
second wrong "missing" verdict parks the step for the CEO, and the rework's answer
replaces whatever the first attempt produced (a capped tool loop's partial result
and its cost note included). Precision therefore beats recall here — code only
demands what it can be sure the criteria demand, see `demanded_entities`.

Imports `listed_entities` from `sprint_runner` rather than copying it — the entity
grammar (parenthesised subjects beat colon attributes, etc.) was hardened by real
incidents and must not fork. The sprint runner itself is NOT modified.
"""

from __future__ import annotations

import logging
import re

from my_crew.runtime.sprint_runner import _capitalised_name_word, listed_entities

logger = logging.getLogger(__name__)

#: An illustrative list — "(ví dụ: suy giảm chất lượng code, quá tải công việc)",
#: "chẳng hạn: standup, retro" — names things the author had in mind, not things
#: the result must contain. Three live steps were parked in one run because the
#: decomposer writes acceptance this way and the checker read each example as a
#: named demand. The marker must open the clause: "3 ví dụ" (a count) stays.
_EXAMPLE_CLAUSE_RE = re.compile(
    r"\(\s*(?:ví dụ|vd|e\.g\.|chẳng hạn|như)\b[^)]*\)"
    r"|\b(?:ví dụ|vd|e\.g\.|chẳng hạn)\s*:[^.\n]*",
    re.IGNORECASE,
)


def demanded_entities(criteria: str) -> list[str]:
    """The names in `criteria` that a result can be held to by substring search.

    Two filters over `listed_entities`, both about what a literal match can prove:

    - example clauses are dropped before parsing — an illustration is not a demand;
    - only NAMES survive — an item with a capitalised (or numeric) word, the same
      discriminator the sprint uses to tell "Shopee" from "giá gói cá nhân". A
      lowercase item is an attribute phrase ("có điểm khởi đầu", "giải pháp/cách
      duy trì") that a result satisfies in its own words, so its presence is the
      LLM checker's call, never a substring's.
    """
    cleaned = _EXAMPLE_CLAUSE_RE.sub("", criteria or "")
    out: list[str] = []
    for entity in listed_entities(cleaned):
        name = entity.strip()
        if name and any(_capitalised_name_word(w) for w in name.split()):
            out.append(name)
    return out


def entity_coverage(criteria: str, artifact: str) -> list[str]:
    """Entities demanded by `criteria` that `artifact` never mentions.

    Matching is deliberately loose — case-insensitive substring, same as the
    sprint's `coverage_gaps` — because a strict matcher would miss aliases
    constantly. No demanded entity in the criteria ⇒ no gaps (fail-open).
    """
    text = (artifact or "").lower()
    return [name for name in demanded_entities(criteria) if name.lower() not in text]


#: An explicit quantity demand in acceptance prose — "liệt kê 5 xu hướng",
#: "ít nhất 3 ví dụ", "tối thiểu 2 nguồn", "đủ 4 mục". Only these lead-ins count:
#: a bare number ("bảng 2 cột", "quý 3") is NOT a quantity contract. Neither is an
#: AMOUNT after the same lead-in — "cộng đúng 90 triệu", "ít nhất 20%", "đủ 1,5 tỷ"
#: name a sum to reach, not a number of list lines, so a unit or decimal right after
#: the digits disqualifies the match.
_MIN_ITEMS_RE = re.compile(
    r"(?:liệt kê(?:\s+đúng)?|ít nhất|tối thiểu|đủ|đúng)\s+(\d{1,2})\b"
    r"(?!\s*(?:[.,]\d|%|tr\b|triệu|tỷ|tỉ|nghìn|ngàn|k\b|đ\b|đồng|vnd|usd|\$))",
    re.IGNORECASE,
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
    - entity coverage: every NAME the acceptance enumerates must be mentioned;
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
        entities = demanded_entities(acceptance)
        if entities and not entity_coverage(acceptance, artifact):
            facts.append(
                f"đủ {len(entities)}/{len(entities)} thực thể nêu trong tiêu chí "
                "đều được nhắc trong kết quả"
            )
        need = _required_min_items(acceptance)
        if need >= 2:
            have = len(_LIST_ITEM_RE.findall(artifact or ""))
            if have >= need:
                # Phrased as "not fewer than", never "the criteria demand N": measured
                # live, "(tiêu chí đòi 2)" next to 28 counted lines read to the grader
                # as "the criteria want two, this has 28" and became a failure.
                facts.append(
                    f"kết quả có {have} dòng dạng danh sách, không ít hơn con số tối "
                    f"thiểu {need} mà tiêu chí nêu (nhiều dòng hơn KHÔNG phải lỗi)"
                )
        if not facts:
            return ""
        return "CODE ĐÃ KIỂM (dữ kiện đo bằng máy, không phải nhận định): " + "; ".join(facts) + "."
    except Exception as exc:  # noqa: BLE001 — same fail-open contract as the gaps check
        logger.warning("deterministic facts line failed, skipping: %s", exc)
        return ""
