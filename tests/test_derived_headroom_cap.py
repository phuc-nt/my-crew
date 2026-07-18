"""Derived cost headroom (v13 M34): no reservation/ledger table — `spawn_headroom_usd`
re-derives "how much is committed right now" from `Σ(actual cost of done/etc steps)` +
`Σ(estimate over steps currently 'running')` on every call, so it can never leak on
kill/timeout/paused/crash/retry — there is no separate row to forget to release. These
tests exercise that leak-freedom through the real dispatch path (`run_one_tick`), not
just `team_task_cost.spawn_headroom_usd` in isolation (a second, narrower unit-level
check of the pure function itself lives in `tests/test_team_task_cost.py` if present).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from my_crew.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker, run_one_tick
from my_crew.agent.task_decomposition import MAX_STEPS, decomposition_content_hash
from my_crew.runtime.team_task_cost import spawn_headroom_usd, step_cost_estimate_usd
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


def _store(tmp_path, **kw) -> TeamTaskStore:
    return TeamTaskStore(tmp_path / "team_tasks.sqlite3", **kw)


def _content_hash(steps: list[dict]) -> str:
    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(
            step_id=s["step_id"], title=s["title"], assigned_to=s["assigned_to"],
            deps=tuple(s.get("deps", ())),
        )
        for s in steps
    ]))


def _plan(store: TeamTaskStore, task_id="t1", steps=None) -> None:
    steps = steps or [
        {"step_id": "s1", "title": "A", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s2", "title": "B", "assigned_to": "agent-b", "deps": []},
    ]
    store.create_task(task_id=task_id, title="demo task", original_request="lam demo")
    store.set_plan(task_id, steps, plan_hash=_content_hash(steps))


def _deps(store, **overrides) -> CoordinatorDeps:
    base = dict(
        store=store,
        retry_tracker=in_memory_retry_tracker(),
        cost_cap_usd=2.0,
        spawn_step=lambda task, step, attempt_id: 4242,
        pid_alive=lambda pid: True,
        kill_pid=lambda pid, attempt_id: None,
        aggregate=lambda task: ("done summary", 0.01),
        deliver_room=lambda task, summary: None,
        escalate=lambda task, step, kind, msg: None,
        now=lambda: datetime.now(UTC),
    )
    base.update(overrides)
    return CoordinatorDeps(**base)


# --- pure function: the formula itself ------------------------------------------------


def test_step_cost_estimate_is_cap_over_max_steps():
    assert step_cost_estimate_usd(7.0, max_steps=7) == 1.0
    assert step_cost_estimate_usd(2.0, max_steps=MAX_STEPS) == pytest.approx(2.0 / MAX_STEPS)


def test_step_cost_estimate_falls_back_to_cap_when_max_steps_not_positive():
    assert step_cost_estimate_usd(2.0, max_steps=0) == 2.0


def test_headroom_subtracts_actual_spend_and_running_estimates(tmp_path):
    store = _store(tmp_path)
    _plan(store, steps=[
        {"step_id": "s1", "title": "A", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s2", "title": "B", "assigned_to": "agent-a", "deps": []},
    ])
    store.reserve_step("t1", "s1")
    store.mark_done("t1", "s1", cost_usd=0.3)
    store.reserve_step("t1", "s2")  # s2 now 'running', not yet done
    task = store.get("t1")
    headroom = spawn_headroom_usd(store, task, cap_usd=2.0, step_estimate_usd=0.5)
    # 2.0 cap - 0.3 actual (done) - 0.5 estimate (s2 running) = 1.2
    assert headroom == pytest.approx(1.2)


def test_awaiting_approval_does_not_count_toward_headroom(tmp_path):
    """A step paused on a Lop B gate releases its headroom back to the task while it
    waits — only genuinely 'running' steps reserve estimate."""
    store = _store(tmp_path)
    _plan(store, steps=[
        {"step_id": "s1", "title": "A", "assigned_to": "agent-a", "deps": []},
    ])
    store.reserve_step("t1", "s1")
    store.mark_awaiting_approval("t1", "s1")
    task = store.get("t1")
    headroom = spawn_headroom_usd(store, task, cap_usd=2.0, step_estimate_usd=0.5)
    assert headroom == pytest.approx(2.0)  # no deduction for the paused step


# --- leak-freedom through the real dispatch path --------------------------------------


def test_headroom_releases_when_running_step_completes(tmp_path):
    """A step that finishes 'running' -> 'done' releases its ESTIMATE from headroom;
    only its ACTUAL recorded cost remains counted — no leftover reservation row exists
    to forget, because there is no reservation row at all."""
    store = _store(tmp_path)
    _plan(store, steps=[
        {"step_id": "s1", "title": "A", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s2", "title": "B", "assigned_to": "agent-a", "deps": []},
    ])
    estimate = step_cost_estimate_usd(2.0, max_steps=MAX_STEPS)

    store.reserve_step("t1", "s1")
    task_mid_flight = store.get("t1")
    headroom_while_running = spawn_headroom_usd(
        store, task_mid_flight, cap_usd=2.0, step_estimate_usd=estimate,
    )
    assert headroom_while_running == pytest.approx(2.0 - estimate)

    # s1 finishes for a cost well BELOW its conservative estimate
    store.mark_done("t1", "s1", cost_usd=estimate / 10)
    task_after = store.get("t1")
    headroom_after = spawn_headroom_usd(store, task_after, cap_usd=2.0, step_estimate_usd=estimate)
    # only the tiny actual cost remains — the estimate reservation is gone, not leaked
    assert headroom_after == pytest.approx(2.0 - estimate / 10)
    assert headroom_after > headroom_while_running


def test_headroom_releases_on_kill_timeout(tmp_path):
    """A step killed for lease timeout (`mark_timeout`) must release its estimate —
    the SAME status-transition write that already has to happen for the timeout
    lifecycle is what frees the headroom; nothing extra to reconcile."""
    store = _store(tmp_path)
    _plan(store, steps=[{"step_id": "s1", "title": "A", "assigned_to": "agent-a", "deps": []}])
    estimate = step_cost_estimate_usd(2.0, max_steps=MAX_STEPS)

    attempt_id = store.reserve_step("t1", "s1")
    store.record_spawn("t1", "s1", 111)
    headroom_running = spawn_headroom_usd(
        store, store.get("t1"), cap_usd=2.0, step_estimate_usd=estimate,
    )
    assert headroom_running == pytest.approx(2.0 - estimate)

    killed = []
    result = run_one_tick(_deps(
        store, cost_cap_usd=2.0,
        pid_alive=lambda pid: True,  # alive but lease expired
        kill_pid=lambda pid, aid: killed.append((pid, aid)),
        now=lambda: datetime(2999, 1, 1, tzinfo=UTC),  # forces lease_expired=True
        escalate=lambda task, step, kind, msg: None,
    ))
    assert result.action == "timeout_escalated"
    assert killed == [(111, attempt_id)]

    headroom_after_kill = spawn_headroom_usd(
        store, store.get("t1"), cap_usd=2.0, step_estimate_usd=estimate,
    )
    # timeout is a terminal status (not 'running') -> its estimate is fully released,
    # and mark_timeout records no cost, so headroom goes back to the full cap.
    assert headroom_after_kill == pytest.approx(2.0)


def test_headroom_releases_on_dead_pid_retry(tmp_path):
    """A dead-pid step gets re-reserved (still 'running' under a NEW attempt) — the
    estimate stays reserved across the retry (it is still genuinely in flight), proving
    headroom tracks CURRENT state, not a stale one-time reservation snapshot."""
    store = _store(tmp_path)
    _plan(store, steps=[{"step_id": "s1", "title": "A", "assigned_to": "agent-a", "deps": []}])
    estimate = step_cost_estimate_usd(2.0, max_steps=MAX_STEPS)

    store.reserve_step("t1", "s1")
    store.record_spawn("t1", "s1", 111)

    respawned = []
    result = run_one_tick(_deps(
        store, cost_cap_usd=2.0,
        pid_alive=lambda pid: False,  # dead pid, no outcome artifact
        spawn_step=lambda task, step, attempt_id: respawned.append(step.step_id) or 222,
    ))
    assert result.action == "spawned"  # retry re-spawns immediately
    assert respawned == ["s1"]

    headroom_after_retry = spawn_headroom_usd(
        store, store.get("t1"), cap_usd=2.0, step_estimate_usd=estimate,
    )
    # exactly ONE estimate still reserved (the retried attempt), not two — no double
    # counting from the dead attempt plus the new one.
    assert headroom_after_retry == pytest.approx(2.0 - estimate)


def test_headroom_gate_defers_second_spawn_without_hard_stalling_the_task(tmp_path):
    """Two steps ready, concurrency=2, but the cap only leaves room for ONE step's
    estimate — the first spawns, the second is deferred to a later tick (once the
    first completes and its estimate is released). Deferring must NOT stall the task;
    that is `check_cost_cap`'s job on ACTUAL spend only, checked once before dispatch."""
    store = _store(tmp_path)
    _plan(store, steps=[
        {"step_id": "s1", "title": "A", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s2", "title": "B", "assigned_to": "agent-a", "deps": []},
    ])
    cap = 2.0
    estimate = step_cost_estimate_usd(cap, max_steps=MAX_STEPS)
    # `cap` always covers exactly MAX_STEPS estimates (estimate = cap / MAX_STEPS), so
    # scaling the cap alone can never leave "room for 1 but not 2" — pre-spend actual
    # cost instead, leaving headroom = 1.5 estimates: room for exactly one more spawn.
    store.record_task_cost("t1", decompose=cap - estimate * 1.5)
    spawned = []
    result = run_one_tick(_deps(
        store, cost_cap_usd=cap, concurrency=2,
        spawn_step=lambda task, step, attempt_id: spawned.append(step.step_id) or 999,
    ))
    assert result.action != "cap_exceeded"  # not the hard stop (nothing spent yet)
    assert result.action == "spawned"
    assert spawned == ["s1"]  # only the first fit; s2 deferred, not dropped
    task = store.get("t1")
    assert task.status in ("open", "running")  # NOT stalled
    statuses = {s.step_id: s.status for s in task.steps}
    assert statuses["s1"] == "running"
    assert statuses["s2"] == "pending"
