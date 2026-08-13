"""In-flight brake (`team_task_halt`): a task that leaves the dispatch path (cap
breach, cancel) must not keep billing through steps already running — kill the
worker (identity-guarded), mark the row failed (attempt-guarded), free the desk.
"""

from __future__ import annotations

import pytest

from my_crew.runtime.team_task_halt import halt_running_steps, run_cancel_reap_sweep
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    """Halt appends real office-room events — pin the shared data root to tmp_path
    so no test touches the real install's .data."""
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


def _store(tmp_path) -> TeamTaskStore:
    return TeamTaskStore(tmp_path / "team_tasks.sqlite3")


def _task_with_steps(store: TeamTaskStore, task_id="t1", n_steps=2) -> None:
    steps = [
        {"step_id": f"s{i}", "title": f"step {i}", "assigned_to": "agent-a", "deps": []}
        for i in range(1, n_steps + 1)
    ]
    store.create_task(task_id=task_id, title="demo task", original_request="lam demo")
    # No tick runs in these tests, so the dispatch-time hash is never recomputed —
    # an arbitrary literal is fine here (unlike the coordinator-graph tests).
    store.set_plan(task_id, steps, plan_hash="x")


def _start_step(store: TeamTaskStore, task_id: str, step_id: str, pid: int) -> str:
    attempt_id = store.reserve_step(task_id, step_id)
    store.record_spawn(task_id, step_id, pid)
    return attempt_id


# --- halt_running_steps ---------------------------------------------------------------


def test_halt_kills_running_steps_and_leaves_pending_alone(tmp_path):
    store = _store(tmp_path)
    _task_with_steps(store, n_steps=2)
    attempt = _start_step(store, "t1", "s1", pid=777)  # s2 stays pending
    killed = []

    halted = halt_running_steps(
        store, store.get("t1"),
        kill_pid=lambda pid, attempt_id: killed.append((pid, attempt_id)),
        note="vượt trần chi phí",
    )

    assert halted == 1
    assert killed == [(777, attempt)]
    assert store.get_step("t1", "s1").status == "failed"
    assert store.get_step("t1", "s2").status == "pending"


def test_halt_attempt_guard_lets_a_raced_worker_finish_win(tmp_path):
    """Snapshot shows the step running, but the worker lands its own terminal write
    before the halt — the attempt-guarded mark_failed must no-op, the done result
    (and its recorded cost) stays the truth, and the halted count excludes it."""
    store = _store(tmp_path)
    _task_with_steps(store, n_steps=1)
    _start_step(store, "t1", "s1", pid=777)
    snapshot = store.get("t1")  # still shows s1 running
    store.mark_done("t1", "s1", cost_usd=0.01)  # worker finishes first

    halted = halt_running_steps(
        store, snapshot, kill_pid=lambda pid, attempt_id: None, note="vượt trần chi phí",
    )

    assert halted == 0
    assert store.get_step("t1", "s1").status == "done"


def test_halt_kill_raising_still_fails_the_row(tmp_path):
    """The kill is best-effort (pid may be gone already); the row write is the truth
    and must land even when the signal path blows up."""
    store = _store(tmp_path)
    _task_with_steps(store, n_steps=1)
    _start_step(store, "t1", "s1", pid=777)

    def _boom(pid, attempt_id):
        raise OSError("no such process")

    halted = halt_running_steps(
        store, store.get("t1"), kill_pid=_boom, note="vượt trần chi phí",
    )

    assert halted == 1
    assert store.get_step("t1", "s1").status == "failed"


# --- run_cancel_reap_sweep ------------------------------------------------------------


def test_cancel_reap_sweep_reaps_cancelled_task_and_is_idempotent(tmp_path):
    store = _store(tmp_path)
    _task_with_steps(store, n_steps=2)
    attempt = _start_step(store, "t1", "s1", pid=888)
    store.set_task_status("t1", "cancelled")
    killed = []

    first = run_cancel_reap_sweep(
        store, kill_pid=lambda pid, attempt_id: killed.append((pid, attempt_id)),
    )
    second = run_cancel_reap_sweep(
        store, kill_pid=lambda pid, attempt_id: killed.append((pid, attempt_id)),
    )

    assert first == 1
    assert second == 0  # reaped task no longer matches the query
    assert killed == [(888, attempt)]
    assert store.get_step("t1", "s1").status == "failed"


def test_cancel_reap_sweep_leaves_live_and_stalled_tasks_alone(tmp_path):
    """Only `cancelled` tasks are reaped: a running task's workers are live work, and
    a stalled task's in-flight steps stay resumable (deliberate — see module docstring)."""
    store = _store(tmp_path)
    _task_with_steps(store, task_id="live", n_steps=1)
    _start_step(store, "live", "s1", pid=111)
    _task_with_steps(store, task_id="parked", n_steps=1)
    _start_step(store, "parked", "s1", pid=222)
    store.set_task_status("parked", "stalled")
    killed = []

    total = run_cancel_reap_sweep(
        store, kill_pid=lambda pid, attempt_id: killed.append(pid),
    )

    assert total == 0
    assert killed == []
    assert store.get_step("live", "s1").status == "running"
    assert store.get_step("parked", "s1").status == "running"
