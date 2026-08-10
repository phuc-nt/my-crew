"""Two ticks racing on the SAME `pending` step must produce exactly ONE worker.

This is not a theoretical configuration. A tick that spawns also touches the poke file
(`spawned` is in `tick_poke._POKE_WORTHY_ACTIONS`), and the service launches the poked
tick on its own thread, in its own process, off its own snapshot. Both ticks then read
the step as `pending` and both reach `reserve_and_spawn`. Observed live on a sprint task:
two `action=spawned` lines for one step, two worker processes, one of which failed
`verify_attempt` and died as a rejected no-op after burning a process.

The fix is a conditional claim in SQL (`reserve_step(..., only_if_pending=True)`), so
the tests here drive `reserve_and_spawn` directly with an interleaving that the
in-process ticker cannot otherwise produce.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from my_crew.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker
from my_crew.agent.coordinator_nodes.tick_actions import reserve_and_spawn
from my_crew.agent.task_decomposition import decomposition_content_hash
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


def _content_hash(steps: list[dict]) -> str:
    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(
            step_id=s["step_id"], title=s["title"], assigned_to=s["assigned_to"],
            deps=tuple(s.get("deps", ())),
        )
        for s in steps
    ]))


def _planned_store(tmp_path) -> TeamTaskStore:
    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    steps = [{"step_id": "s1", "title": "A", "assigned_to": "agent-a", "deps": []}]
    store.create_task(task_id="t1", title="demo", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    return store


def _deps(store, spawned, **overrides) -> CoordinatorDeps:
    base = dict(
        store=store,
        retry_tracker=in_memory_retry_tracker(),
        cost_cap_usd=2.0,
        spawn_step=lambda task, step, attempt_id: (
            spawned.append((step.step_id, attempt_id)) or 4242
        ),
        pid_alive=lambda pid: True,
        kill_pid=lambda pid, attempt_id: None,
        aggregate=lambda task: ("done summary", 0.01),
        deliver_room=lambda task, summary: None,
        escalate=lambda task, step, kind, msg: None,
        now=lambda: datetime.now(UTC),
    )
    base.update(overrides)
    return CoordinatorDeps(**base)


def test_the_second_tick_on_the_same_pending_step_does_not_spawn(tmp_path):
    """Both ticks hold a snapshot taken while the step was still `pending`. The first
    claim wins; the second must see the row is no longer `pending`, decline, and report
    `none` — the action deliberately kept OUT of the poke-worthy set so a lost race also
    terminates the poke chain instead of feeding it."""
    store = _planned_store(tmp_path)
    spawned: list[tuple[str, str]] = []
    deps = _deps(store, spawned)

    # One snapshot, read by both ticks — this is what makes them race.
    task = store.get(task_id="t1")
    step = task.steps[0]
    assert step.status == "pending"

    first = reserve_and_spawn(deps, task, step)
    second = reserve_and_spawn(deps, task, step)

    assert first.action == "spawned"
    assert second.action == "none"
    assert second.detail == "s1"
    assert len(spawned) == 1, "a lost race must not start a second worker"

    row = store.get(task_id="t1").steps[0]
    assert row.status == "running"
    assert row.attempt_id == spawned[0][1], "the winner's attempt_id is the one on the row"


def test_a_re_reserve_of_a_running_step_is_not_blocked_by_the_guard(tmp_path):
    """The guard applies to a FIRST dispatch only. A retry after a dead pid / expired
    lease targets a `running` row on purpose, and must still mint a fresh attempt_id —
    a pending-only condition would refuse every one of those and strand the step."""
    store = _planned_store(tmp_path)
    spawned: list[tuple[str, str]] = []
    deps = _deps(store, spawned)

    first_attempt = store.reserve_step("t1", "s1")
    store.record_spawn("t1", "s1", 111)

    task = store.get(task_id="t1")
    running_step = task.steps[0]
    assert running_step.status == "running"

    result = reserve_and_spawn(deps, task, running_step)

    assert result.action == "spawned"
    assert len(spawned) == 1
    assert spawned[0][1] != first_attempt, "a retry gets a fresh attempt_id"
    assert store.get(task_id="t1").steps[0].attempt_id == spawned[0][1]


def test_the_second_tick_re_reserving_the_same_expired_step_does_not_spawn(tmp_path):
    """The `pending` guard cannot cover this one: both ticks see a `running` row whose
    lease expired and whose pid is dead, and both decide to retry it. Unguarded, each
    mints a fresh attempt and spawns — and the loser is worse off than in the pending
    race, because its attempt_id gets overwritten, so it never fails `verify_attempt`.
    It just runs, duplicating the work and the spend.

    The attempt_id the tick READ is the condition: once another tick re-reserves, it
    rotates, and this claim must lose."""
    store = _planned_store(tmp_path)
    spawned: list[tuple[str, str]] = []
    deps = _deps(store, spawned)

    store.reserve_step("t1", "s1")
    store.record_spawn("t1", "s1", 111)

    # One snapshot of the dead/expired `running` row, read by both ticks.
    task = store.get(task_id="t1")
    step = task.steps[0]

    first = reserve_and_spawn(deps, task, step)
    second = reserve_and_spawn(deps, task, step)

    assert first.action == "spawned"
    assert second.action == "none"
    assert len(spawned) == 1, "a lost re-reserve race must not start a second worker"
    assert store.get(task_id="t1").steps[0].attempt_id == spawned[0][1]


def test_a_resumed_step_carrying_no_attempt_id_still_dispatches(tmp_path):
    """Nothing to condition on is not the same as losing a race. A non-pending row that
    never held a lease (or a test double that omits the field) must still spawn, or the
    approval/clarify resume paths would silently strand every step they touch."""
    store = _planned_store(tmp_path)
    spawned: list[tuple[str, str]] = []
    store.reserve_step("t1", "s1")
    store.mark_awaiting_approval("t1", "s1")

    task = store.get(task_id="t1")
    step = task.steps[0]
    object.__setattr__(step, "attempt_id", None)

    result = reserve_and_spawn(_deps(store, spawned), task, step)

    assert result.action == "spawned"
    assert len(spawned) == 1


def test_an_unknown_step_still_raises_rather_than_reporting_a_lost_race(tmp_path):
    """"Someone else claimed it" and "no such step" must stay distinguishable: the
    former is normal under concurrency, the latter is a bug and has to surface."""
    store = _planned_store(tmp_path)
    task = store.get(task_id="t1")
    ghost = SimpleNamespace(
        step_id="ghost", title="G", assigned_to="agent-a", deps=(), status="pending",
    )
    with pytest.raises(ValueError, match="unknown team step"):
        reserve_and_spawn(_deps(store, []), task, ghost)
