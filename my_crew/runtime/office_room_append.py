"""try/degrade wrapper for `office_room_store.append` calls made from the team-task
pipeline (v12 M29): coordinator ticker, `ops_assign_team_task`, `team_step_runner`.

A room-store append is a NICE-TO-HAVE observability write, never a step in the pipeline
itself — the coordinator/step/CEO-command flow must complete identically whether or not
the append lands (a locked file, a disk-full data dir, or a bad `kind` must never block
dispatch/step-completion/task-confirm). Every call here therefore swallows its own
exception and logs, matching `team_tick_collaborators.make_escalate`'s "never raises"
contract for the exact same reason.
"""

from __future__ import annotations

import logging

from my_crew.runtime.office_room_store import OfficeRoomStore, office_room_db_path
from my_crew.runtime.team_task_paths import team_tasks_root

logger = logging.getLogger(__name__)


def room_for_task(task_id: str) -> str:
    """Effective WORKROOM for a task's room events (v16): the task's `room_id` when set
    (a child task assigned inside an existing room), else the task's own id (every
    pre-v16 task and every task assigned outside a room). ALL team-task event writers
    route their room through this ONE helper so the routing rule lives in one place.
    Degrade-not-raise: any store hiccup falls back to task_id — an event landing in the
    task's own room is always a safe default (that IS the pre-v16 behavior)."""
    try:
        from my_crew.runtime.team_task_paths import team_tasks_db_path
        from my_crew.runtime.team_task_store import TeamTaskStore

        store = TeamTaskStore(team_tasks_db_path())
        try:
            task = store.get(task_id)
        finally:
            store.close()
        if task is not None and getattr(task, "room_id", ""):
            return task.room_id
    except Exception:  # noqa: BLE001 — routing must never block an event append
        logger.warning("room_for_task(%s) failed — falling back to task room", task_id)
    return task_id


def append_office_event(
    room_id: str, *, author: str, kind: str, body: dict, also_office: bool = False,
) -> None:
    """Open the store, append one event, close — best-effort, never raises.

    Opens a fresh connection per call rather than holding one open across the caller's
    lifetime: callers here are short-lived (one tick / one CEO command / one step), so
    the connection-open cost is negligible next to the LLM/subprocess work around it,
    and a fresh connection sidesteps any lifetime-management question entirely.
    """
    try:
        store = OfficeRoomStore(office_room_db_path(team_tasks_root()))
        try:
            store.append(room_id, author=author, kind=kind, body=body, also_office=also_office)
        finally:
            store.close()
    except Exception:  # noqa: BLE001 — an office-room append must never block the pipeline
        logger.warning(
            "office-room append failed (room=%s kind=%s) — continuing without it",
            room_id, kind, exc_info=True,
        )
