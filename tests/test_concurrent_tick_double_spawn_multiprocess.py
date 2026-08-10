"""The double-spawn guard under REAL process contention, not a scripted interleaving.

`test_concurrent_tick_double_spawn.py` drives `reserve_and_spawn` twice in a row on one
snapshot. That proves the decision logic, but it cannot prove the claim is atomic: the
calls never overlap, so a guard that only works when nothing is racing would pass it.
Production is the opposite shape — the ticker and each poked tick are separate OS
processes, each with its OWN sqlite connection to the same WAL file, all issuing their
UPDATE at once.

Threads cannot stand in for that. `TeamTaskStore` opens with `check_same_thread=False`
and several threads sharing one connection raise `InterfaceError` from the driver
itself, which masks the very thing under test. So these tests fork real processes.

Load-bearing check: with `only_if_attempt` removed from `reserve_and_spawn`, the
re-dispatch case below spawns one worker PER PROCESS (8 duplicate LLM runs for one
step, at 8x the spend). The pending case still passes, which is exactly why the
re-dispatch hole survived the first round of fixes.
"""

from __future__ import annotations

import multiprocessing as mp
import pathlib
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from my_crew.agent.task_decomposition import decomposition_content_hash
from my_crew.runtime.team_task_store import TeamTaskStore

#: Enough contention to make a lost race overwhelmingly likely if the claim is not
#: atomic, while still starting fast enough for a unit-test suite.
RACERS = 6


def _tick_worker(repo: str, db_dir: str, task_id: str, step_id: str, barrier, out) -> None:
    """One tick, in its own process, off its own snapshot and its own connection.

    Module-level (not a closure) because macOS spawns rather than forks, so the target
    must be importable and picklable.
    """
    sys.path.insert(0, repo)
    import my_crew.runtime.team_task_paths as ttp

    ttp.DATA_DIR = pathlib.Path(db_dir)
    from my_crew.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker
    from my_crew.agent.coordinator_nodes.tick_actions import reserve_and_spawn
    from my_crew.runtime.team_task_store import TeamTaskStore as Store

    store = Store(pathlib.Path(db_dir) / "team_tasks.sqlite3")
    task = store.get(task_id=task_id)
    step = next(s for s in task.steps if s.step_id == step_id)

    spawned: list[str] = []
    deps = CoordinatorDeps(
        store=store,
        retry_tracker=in_memory_retry_tracker(),
        cost_cap_usd=2.0,
        spawn_step=lambda t, s, attempt_id: (spawned.append(attempt_id) or 4242),
        pid_alive=lambda pid: True,
        kill_pid=lambda pid, attempt_id: None,
        aggregate=lambda t: ("done", 0.01),
        deliver_room=lambda t, summary: None,
        escalate=lambda t, s, kind, msg: None,
        now=lambda: datetime.now(UTC),
    )
    # Every process holds its snapshot before any of them claims — that is the race.
    barrier.wait()
    try:
        action = reserve_and_spawn(deps, task, step).action
    except Exception as exc:  # noqa: BLE001 — reported, not raised, from a child
        action = f"EXC:{type(exc).__name__}:{exc}"
    out.put((action, list(spawned)))


def _race(db_dir: pathlib.Path, task_id: str, step_id: str) -> tuple[list[str], list[str]]:
    repo = str(pathlib.Path(__file__).resolve().parent.parent)
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(RACERS)
    out = ctx.Queue()
    procs = [
        ctx.Process(
            target=_tick_worker,
            args=(repo, str(db_dir), task_id, step_id, barrier, out),
        )
        for _ in range(RACERS)
    ]
    for p in procs:
        p.start()
    actions: list[str] = []
    spawns: list[str] = []
    # Drain BEFORE joining: a child blocks on put() until its queue is read, so
    # joining first would deadlock.
    for _ in range(RACERS):
        action, spawned = out.get(timeout=120)
        actions.append(action)
        spawns.extend(spawned)
    for p in procs:
        p.join(timeout=60)
    return actions, spawns


@pytest.fixture()
def planned_store(tmp_path):
    steps = [{"step_id": "s1", "title": "A", "assigned_to": "agent-a", "deps": []}]
    plan_hash = decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(step_id="s1", title="A", assigned_to="agent-a", deps=()),
    ]))
    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    store.create_task(task_id="t1", title="demo", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=plan_hash)
    return store


def test_many_processes_claiming_one_pending_step_start_exactly_one_worker(
    planned_store, tmp_path,
):
    actions, spawns = _race(tmp_path, "t1", "s1")

    assert not [a for a in actions if a.startswith("EXC:")], f"unexpected errors: {actions}"
    assert len(spawns) == 1, f"expected 1 worker, got {len(spawns)}: {actions}"
    assert sorted(actions) == ["none"] * (RACERS - 1) + ["spawned"]
    assert planned_store.get(task_id="t1").steps[0].attempt_id == spawns[0]


def test_many_processes_re_dispatching_one_running_step_start_exactly_one_worker(
    planned_store, tmp_path,
):
    """The case the pending-only guard could not cover, and the expensive one: the
    loser of a re-dispatch race has its attempt_id overwritten, so it never fails
    `verify_attempt` — it just runs, duplicating the work and the spend."""
    planned_store.reserve_step("t1", "s1")
    planned_store.record_spawn("t1", "s1", 111)

    actions, spawns = _race(tmp_path, "t1", "s1")

    assert not [a for a in actions if a.startswith("EXC:")], f"unexpected errors: {actions}"
    assert len(spawns) == 1, f"expected 1 worker, got {len(spawns)}: {actions}"
    assert sorted(actions) == ["none"] * (RACERS - 1) + ["spawned"]
    assert planned_store.get(task_id="t1").steps[0].attempt_id == spawns[0]
