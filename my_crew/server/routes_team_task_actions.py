"""One-click unstick + cancel for a team task (v88 P3) — REST wrappers over the
existing chat-ops recovery commands, so a stalled task can be handled from the Work
board in ≤2 clicks instead of "gõ đúng câu" to the coordinator.

Every mutating route here is a THIN wrapper over `my_crew.agent.ops_stalled_task`'s
three stall recoveries (`run_retry_stalled_step` / `run_accept_stalled_result` /
`run_drop_stalled_step`) plus one new store primitive (`TeamTaskStore.cancel_task`,
mirroring `confirm_plan`'s TOCTOU-proof single-guarded-UPDATE shape — see that
method's docstring). The route layer NEVER reads a step/task's status before acting:
the ops layer (or the guarded UPDATE) is the single source of truth for "is this
allowed right now", so two concurrent requests racing the same row always resolve to
exactly one winner + one clean rejection, never a double-apply.

Cancel design: `cancel_task` flips the row, then this route calls
`run_cancel_reap_sweep` INLINE (not left to the next tick) so a task's running step
stops immediately instead of up to ~60s later — the sweep is idempotent (module
docstring: "reaped task no longer matches the query") so calling it here and again on
the next tick is a harmless no-op the second time.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from my_crew.runtime.team_task_paths import team_tasks_db_path
from my_crew.runtime.team_task_store import TeamTask, TeamTaskStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/team-tasks", tags=["team-task-actions"])


def _open_store() -> TeamTaskStore:
    return TeamTaskStore(team_tasks_db_path())


def _task_shape(task: TeamTask) -> dict:
    """The refreshed-task payload every mutation returns, so the FE invalidates +
    repaints from one response instead of a follow-up GET. Mirrors the fields the
    board card + task detail already read (status drives the FE's stalled-panel
    visibility; steps carry each step's own status for the retry/accept/drop targets)."""
    return {
        "task_id": task.id,
        "title": task.title,
        "status": task.status,
        "pic_id": task.pic_id,
        "room_id": task.room_id or task.id,
        "steps": [
            {
                "step_id": s.step_id, "title": s.title, "status": s.status,
                "step_type": s.step_type, "assigned_to": s.assigned_to,
            }
            for s in task.steps
        ],
    }


def _require_task(store: TeamTaskStore, task_id: str) -> TeamTask:
    task = store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"không tìm thấy việc đội `{task_id}`")
    return task


@router.post("/{task_id}/steps/{step_id}/retry")
def retry_step(task_id: str, step_id: str) -> dict:
    """Buy the stalled step(s) one more attempt (rework round or re-dispatch).

    `step_id` is accepted for a stable per-step URL/double-fire guard on the FE, but
    `run_retry_stalled_step` itself derives which steps need the retry from the task's
    own state (its only required slot is `task_id`) — passing an unrelated step_id
    cannot retry a different step than the one(s) actually stalled. Batch semantics: if
    a task has more than one dead step, this retries ALL of them, not just one — the
    ops layer's intended "unstick the whole task" recovery, not a per-step action. The
    FE renders one cluster per task and sends a `_` placeholder, so this is not
    surfaced as a per-step promise.
    """
    import sqlite3

    from my_crew.agent.ops_stalled_task import run_retry_stalled_step

    store = _open_store()
    try:
        _require_task(store, task_id)
    finally:
        store.close()
    try:
        run_retry_stalled_step({"task_id": task_id})
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except sqlite3.IntegrityError:
        # Two retries raced: both snapshots missed the rework row, both tried to insert
        # the same derived step_id, and this one lost the UNIQUE(task_id, step_id) write.
        # The winner already reopened the task, so this is a clean "someone beat you"
        # rejection — the 409 the route contract promises, not a 500.
        raise HTTPException(
            status_code=409,
            detail="việc này vừa được gỡ kẹt bởi một thao tác khác",
        ) from None
    return _refreshed(task_id)


@router.post("/{task_id}/steps/{step_id}/accept")
def accept_step(task_id: str, step_id: str) -> dict:
    """Accept a review-stalled task's existing deliverable and let it complete."""
    from my_crew.agent.ops_stalled_task import run_accept_stalled_result

    store = _open_store()
    try:
        _require_task(store, task_id)
    finally:
        store.close()
    try:
        run_accept_stalled_result({"task_id": task_id})
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return _refreshed(task_id)


@router.post("/{task_id}/steps/{step_id}/drop")
def drop_step(task_id: str, step_id: str) -> dict:
    """Give up on the dead step(s) so the rest of the DAG can finish without them.

    Same batch semantics as retry: drops ALL dead steps of the task, not only one; the
    URL's `step_id` is the FE's stable-URL/double-fire handle, not a per-step selector.
    """
    from my_crew.agent.ops_stalled_task import run_drop_stalled_step

    store = _open_store()
    try:
        _require_task(store, task_id)
    finally:
        store.close()
    try:
        run_drop_stalled_step({"task_id": task_id})
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return _refreshed(task_id)


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str) -> dict:
    """Cancel a LIVE team task (open/running/stalled). TOCTOU-proof: `cancel_task`'s
    guarded UPDATE is the only status check — a task already terminal (done/cancelled)
    or still an unconfirmed draft (`planning`, use the assign-composer's own cancel)
    reports 409, never a silent no-op that looks like success."""
    from my_crew.runtime.team_task_halt import run_cancel_reap_sweep
    from my_crew.runtime.team_tick_runner import _kill_pid

    store = _open_store()
    try:
        task = _require_task(store, task_id)
        if not store.cancel_task(task_id):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"việc `{task_id}` đang ở trạng thái '{task.status}' — không thể huỷ "
                    "(chỉ huỷ được việc đang mở/đang chạy/đang kẹt)"
                ),
            )
        # Immediate reap: a cancelled task's still-running step must not keep billing
        # up to a minute waiting for the next tick (see module docstring). Best-effort
        # hygiene — a failure here is not the cancel's failure, the next tick's
        # `run_cancel_reap_sweep` call covers it either way.
        try:
            run_cancel_reap_sweep(store, kill_pid=_kill_pid)
        except Exception:  # noqa: BLE001 — the cancel itself already committed
            logger.warning("cancel_task: inline reap failed for %s", task_id, exc_info=True)
    finally:
        store.close()
    return _refreshed(task_id)


def _refreshed(task_id: str) -> dict:
    store = _open_store()
    try:
        task = store.get(task_id)
    finally:
        store.close()
    if task is None:  # pragma: no cover — the row cannot vanish mid-request
        raise HTTPException(status_code=404, detail=f"không tìm thấy việc đội `{task_id}`")
    return _task_shape(task)
