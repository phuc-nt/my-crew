"""What a previewed plan will be allowed to do — the pre-authorization card's content.

The composer shows this next to the plan text so the CEO can pre-approve the task's
external actions at confirm time ("duyệt tất cả") instead of being paged per gate later.
Read from the persisted draft (the same rows `confirm_plan` will bind), never from the
preview text, so the card and the run cannot disagree.
"""

from __future__ import annotations

from typing import Any

#: Step flags surfaced verbatim — each one is a capability the run may exercise.
_STEP_FLAGS = ("external_write", "needs_shell", "needs_web", "needs_mail", "needs_review")


def build_assign_manifest(task_id: str) -> dict[str, Any]:
    """Manifest for a drafted task: its steps with their capability flags, plus the count
    of steps that can write outside the company (the ones a pre-authorization covers).
    An unknown/empty id degrades to an empty manifest — the composer then renders no
    card rather than the preview failing."""
    empty: dict[str, Any] = {"steps": [], "external_count": 0}
    if not task_id:
        return empty
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    try:
        task = store.get(task_id)
    finally:
        store.close()
    if task is None:
        return empty
    steps = [
        {
            "step_id": s.step_id,
            "title": s.title,
            "assigned_to": s.assigned_to,
            **{flag: bool(getattr(s, flag, False)) for flag in _STEP_FLAGS},
        }
        for s in task.steps
    ]
    return {"steps": steps, "external_count": sum(1 for s in steps if s["external_write"])}
