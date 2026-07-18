"""Assigned-tasks board API (v6 M15b) — read the board + cancel a task from the web.

Read-only listing of every agent's assigned tasks (open + finished) for the /tasks board,
plus a cancel endpoint. Cancel is a config-level write (flip a task's status in the agent's
store) — same no-auth posture as the other admin write routes (M7), covered by M16 auth
like everything else. Assigning a task stays on the chat path (needs the confirm dialogue);
the board only VIEWS and CANCELS.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from my_crew.runtime.agent_paths import agent_data_dir
from my_crew.runtime.registry import load_registry

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _store_for(agent_id: str):
    from my_crew.runtime.task_scheduling import _store_path
    from my_crew.runtime.task_store import TaskStore

    path = _store_path(agent_data_dir(agent_id))
    if not path.exists():
        return None
    return TaskStore(path)


def _task_json(task) -> dict:
    return {
        "id": task.id,
        "kind": task.kind,
        "params": task.params,
        "status": task.status,
        "created_at": task.created_at,
        "assigned_by": task.assigned_by,
        "history": [{"ts": h.ts, "summary": h.summary, "cost_usd": h.cost_usd}
                    for h in task.history],
    }


@router.get("")
def list_all_tasks() -> dict:
    """Every agent's tasks, grouped by agent — the board's data. Agents with no store are
    omitted (they have no tasks). Read-only; never raises for a missing store."""
    import logging

    out: list[dict] = []
    for entry in load_registry():
        store = _store_for(entry.id)
        if store is None:
            continue
        try:
            tasks = store.list_all()
        except Exception:  # noqa: BLE001 — one corrupt/locked store must not 500 the board
            logging.getLogger(__name__).warning(
                "tasks board: skipping agent %r (store unreadable)", entry.id, exc_info=True
            )
            continue
        finally:
            store.close()
        if tasks:
            out.append({"agent_id": entry.id, "tasks": [_task_json(t) for t in tasks]})
    return {"agents": out}


@router.post("/{agent_id}/{task_id}/cancel")
def cancel_task(agent_id: str, task_id: int) -> dict:
    """Cancel an open task. 404 if the agent has no store / no such task; a task already in
    a terminal state is returned unchanged (idempotent)."""
    try:
        agent_data_dir(agent_id)  # validates the id (path-escape guard) before touching disk
    except ValueError:
        raise HTTPException(status_code=400,
                            detail=f"agent id không hợp lệ: {agent_id!r}") from None
    store = _store_for(agent_id)
    if store is None:
        raise HTTPException(status_code=404, detail=f"agent {agent_id!r} chưa có việc nào")
    try:
        task = store.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"không có việc #{task_id}")
        if task.status in ("open", "running"):
            store.set_status(task_id, "cancelled")
            status = "cancelled"
        else:
            status = task.status  # terminal already — idempotent no-op
    finally:
        store.close()
    return {"agent_id": agent_id, "task_id": task_id, "status": status}
