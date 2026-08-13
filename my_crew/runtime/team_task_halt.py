"""Brake for in-flight steps of a task that has left the dispatch path.

`check_cost_cap` (hard stop on recorded spend) and `spawn_headroom_usd` (derived
pre-spawn gate) only govern NEW spend — neither touches a step already running.
Once a task turns `cancelled` or `stalled` it also drops out of
`list_dispatchable()`, so its running steps are never polled again: each one keeps
its worker process alive, finishes on its own schedule, and bills its cost into the
store. Measured live (task 9b9af162549a): ~$0.05 of a $0.179 total landed AFTER the
cancel — "cancel" blocked new steps but was never a brake on current ones.

This module is that brake, used from exactly two places:

- The coordinator's `cost_cap_exceeded` branch calls `halt_running_steps` inline —
  a breached ceiling means "stop spending NOW", not "stop after the in-flight steps
  drain". Other stall reasons (review exhausted, stuck-step ruling) deliberately do
  NOT halt: those stalls concern one step's churn, the rest of the in-flight work is
  still wanted when the CEO resumes the task.
- The `team-tick` hygiene block runs `run_cancel_reap_sweep` every tick — cancels
  arrive from many surfaces (gateway `team_task_move`, follow-up sweep expiry,
  direct store writes) and routing the kill through every one of them would leak the
  first time a new cancel path forgets it. Deriving "cancelled task with a running
  step" fresh from the tables each tick is correct for every path by construction
  (same no-ledger philosophy as `team_task_cost.spawn_headroom_usd`), at the price
  of one tick of latency.

The kill itself reuses the ticker's pid-reuse-guarded killer (`_kill_pid` verifies
the command line still carries this step's attempt_id before signaling), and the
terminal write is `TeamTaskStore.halt_step` — atomic on attempt_id AND
status='running', so a worker that finished or was re-reserved between our snapshot
and the write wins the race cleanly (see that method's docstring for why the
attempt guard alone isn't enough here).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from my_crew.runtime.office_room_append import append_office_event, room_for_task
from my_crew.runtime.team_task_store import TeamTask, TeamTaskStore

logger = logging.getLogger(__name__)

#: kill_pid(pid, attempt_id) — identity-guarded SIGKILL, best-effort (see
#: `team_tick_runner._kill_pid`). Injected so tests never signal real processes.
KillPid = Callable[[int, str], None]


def halt_running_steps(
    store: TeamTaskStore, task: TeamTask, *, kill_pid: KillPid, note: str,
) -> int:
    """Kill + mark `failed` every `running` step of `task`; returns how many rows
    this call actually terminated (attempt-guarded, so a step whose worker finished
    or was re-reserved since `task` was read counts 0 and is left alone).

    `note` names WHY in the room event ("vượt trần chi phí", "việc đã huỷ") — the
    step event itself stays the existing `step_status failed` vocabulary so the FE
    desk reducer frees the desk without new grammar (same shape as the timeout path).
    """
    halted = 0
    for step in task.steps:
        if step.status != "running":
            continue
        if step.child_pid is not None and step.attempt_id is not None:
            try:
                kill_pid(step.child_pid, step.attempt_id)
            except Exception:  # noqa: BLE001 — the kill is best-effort; the row write is the truth
                logger.warning("halt: kill_pid(%s) raised for %s/%s (bỏ qua)",
                               step.child_pid, task.id, step.step_id, exc_info=True)
        if not store.halt_step(task.id, step.step_id, attempt_id=step.attempt_id):
            continue  # worker's own terminal write (or a newer attempt) won the race
        halted += 1
        append_office_event(
            room_for_task(task.id), author="coordinator", kind="step_status",
            body={"task_title": task.title, "step_title": step.title, "status": "failed",
                  "assigned_to": step.assigned_to, "note": note},
            also_office=True,
        )
    return halted


def run_cancel_reap_sweep(store: TeamTaskStore, *, kill_pid: KillPid) -> int:
    """One hygiene pass: halt the running steps of every `cancelled` task that still
    has any. Idempotent — a reaped task no longer matches the query, so the steady
    state is an empty scan. Returns total steps halted (for the tick log)."""
    total = 0
    for task in store.cancelled_tasks_with_running_steps():
        halted = halt_running_steps(store, task, kill_pid=kill_pid, note="việc đã huỷ")
        if halted:
            logger.info("cancel-reap: task %s — dừng %s bước đang chạy sau khi huỷ",
                        task.id, halted)
        total += halted
    return total
