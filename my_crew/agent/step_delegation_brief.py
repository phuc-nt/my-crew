"""The two brief elements a team-step worker was never shown: its rubric and its scope.

The reference harnesses all hand a delegate the same four things — objective, output
format, boundaries, and the rubric it will be judged on. This graph handed a worker its
title, its artifact line and the deps' hand-off; the `acceptance` the self-check grades
against lived only in `state["acceptance"]`, and the other steps of the plan were
invisible. Two failures follow directly and both are in the MAST specification group:
a step that stops short of a criterion it never read, and a step that redoes (or
pre-empts) a sibling's work because nothing told it where its part ends.

Pure text, no model call. The sprint pipeline already passes acceptance to its own
work call (`build_sprint_work(acceptance=...)`); this block is for the team-step work
and rework prompts.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

ACCEPTANCE_HEADER = "TIÊU CHÍ NGHIỆM THU (bước này được chấm đúng theo đây):"
SIBLINGS_HEADER = "VIỆC CỦA BƯỚC KHÁC (KHÔNG làm ở đây — chỉ bàn giao phần của mình):"
#: A plan is bounded (`MAX_STEPS`), but a runtime split can add sub-rows; six titles is
#: enough to draw the boundary and a longer list would crowd the actual brief.
MAX_SIBLINGS = 6
_TITLE_CAP = 90


def sibling_titles(step, steps: Iterable | None) -> list[str]:
    """Titles of the OTHER content steps of the same task, in the order given.

    Excludes the step itself, `review` rows (a verdict is not work the worker could
    redo) and system-inserted rows (rework/gather rows minted by the runtime, whose
    titles restate a content step already in the list).
    """
    own = str(getattr(step, "step_id", "") or "")
    titles: list[str] = []
    for other in steps or ():
        if own and str(getattr(other, "step_id", "") or "") == own:
            continue
        if str(getattr(other, "step_type", "work") or "work") == "review":
            continue
        if bool(getattr(other, "system_inserted", False)):
            continue
        title = str(getattr(other, "title", "") or "").strip()
        if title:
            titles.append(title)
    return titles


def _clip(title: str) -> str:
    return title if len(title) <= _TITLE_CAP else title[: _TITLE_CAP - 1].rstrip() + "…"


def delegation_brief(acceptance: str, siblings: Sequence[str] = ()) -> str:
    """The brief block: rubric first, then the siblings' scope. "" when both are blank."""
    parts: list[str] = []
    rubric = (acceptance or "").strip()
    if rubric:
        parts.append(f"{ACCEPTANCE_HEADER}\n{rubric}")
    names = [t.strip() for t in siblings if t and t.strip()]
    if names:
        lines = [f"- {_clip(t)}" for t in names[:MAX_SIBLINGS]]
        if len(names) > MAX_SIBLINGS:
            lines.append(f"- … và {len(names) - MAX_SIBLINGS} bước khác")
        parts.append(SIBLINGS_HEADER + "\n" + "\n".join(lines))
    return "\n\n".join(parts)
