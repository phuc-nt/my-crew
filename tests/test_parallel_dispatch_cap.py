"""Parallel dispatch cap (v13 M34): one tick may spawn MORE THAN ONE ready step, up to
`CoordinatorDeps.concurrency` minus however many are already `running` — v12 already
dispatched across separate ticks; this raises the SAME-TICK ceiling from 1 to
`concurrency`. Every assertion here is against fully injectable doubles (no real
subprocess/network/LLM/clock), same convention as `test_coordinator_graph.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from my_crew.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker, run_one_tick
from my_crew.agent.task_decomposition import decomposition_content_hash
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
        {"step_id": "s3", "title": "C", "assigned_to": "agent-a", "deps": []},
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


def test_default_concurrency_two_spawns_two_of_three_ready_steps(tmp_path):
    """Three independent steps ready in the same tick, default concurrency=2 — exactly
    2 spawn, the 3rd waits for a later tick (once a running step frees a slot)."""
    store = _store(tmp_path)
    _plan(store)
    spawned = []
    result = run_one_tick(_deps(
        store, spawn_step=lambda task, step, attempt_id: spawned.append(step.step_id) or 999,
    ))
    assert result.action == "spawned"
    assert len(spawned) == 2
    assert spawned == ["s1", "s2"]  # seq order, same tie-break as the old single-spawn path
    statuses = {s.step_id: s.status for s in store.get(task_id="t1").steps}
    assert statuses["s1"] == "running"
    assert statuses["s2"] == "running"
    assert statuses["s3"] == "pending"


def test_concurrency_one_matches_legacy_single_spawn_detail_format(tmp_path):
    """`concurrency=1` (or a fixture with only one ready step) keeps `TickResult.detail`
    byte-identical to pre-v13's single-spawn format — no ``"; "`` joiner leaks in."""
    store = _store(tmp_path)
    _plan(store, steps=[
        {"step_id": "s1", "title": "A", "assigned_to": "agent-a", "deps": []},
    ])
    result = run_one_tick(_deps(store, concurrency=1))
    assert result.action == "spawned"
    assert result.detail.startswith("s1 attempt=")
    assert ";" not in result.detail


def test_already_running_steps_count_against_the_cap(tmp_path):
    """One step already `running` AND ALIVE (e.g. spawned on a prior tick, pid still
    up, lease not expired) — concurrency=2 means only ONE more slot is free this tick,
    even with 2 more steps ready."""
    store = _store(tmp_path)
    _plan(store)
    attempt_id = store.reserve_step("t1", "s1")
    store.record_spawn("t1", "s1", 111)  # simulate: already running from a prior tick
    spawned = []
    result = run_one_tick(_deps(
        store, spawn_step=lambda task, step, attempt_id: spawned.append(step.step_id) or 999,
        pid_alive=lambda pid: pid == 111,  # s1's pid is genuinely alive
    ))
    assert result.action == "spawned"
    assert spawned == ["s2"]
    assert attempt_id  # sanity: a real lease was minted for s1


def test_concurrency_exhausted_by_running_steps_yields_no_spawn_this_tick(tmp_path):
    """Every concurrency slot already occupied by ALIVE `running` steps -> the ticker
    moves on to poll those running steps instead of ever attempting a new spawn."""
    store = _store(tmp_path)
    _plan(store)
    store.reserve_step("t1", "s1")
    store.record_spawn("t1", "s1", 111)
    store.reserve_step("t1", "s2")
    store.record_spawn("t1", "s2", 222)
    spawned = []
    result = run_one_tick(_deps(
        store, concurrency=2,
        spawn_step=lambda task, step, attempt_id: spawned.append(step.step_id) or 999,
        pid_alive=lambda pid: pid in (111, 222),
    ))
    assert spawned == []
    # both running steps are alive (pid_alive=True, lease not expired) -> nothing to do
    assert result.action == "none"


def test_higher_concurrency_config_spawns_more_in_one_tick(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    spawned = []
    result = run_one_tick(_deps(
        store, concurrency=3,
        spawn_step=lambda task, step, attempt_id: spawned.append(step.step_id) or 999,
    ))
    assert result.action == "spawned"
    assert spawned == ["s1", "s2", "s3"]


def test_review_insert_rule_still_runs_before_dispatch_under_parallel_cap(tmp_path):
    """P2's review-insert rule must still short-circuit dispatch entirely (checked
    BEFORE any ready-step scan) even with concurrency > 1 — a `done` `needs_review`
    step must mint its review row before any OTHER ready step in the same task gets
    spawned this tick."""
    store = _store(tmp_path)
    steps = [
        {"step_id": "s1", "title": "A", "assigned_to": "agent-a", "deps": [],
         "needs_review": True},
        {"step_id": "s2", "title": "B", "assigned_to": "agent-b", "deps": []},
    ]
    store.create_task(task_id="t1", title="demo", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    store.mark_done("t1", "s1")

    spawned = []
    result = run_one_tick(_deps(
        store, concurrency=2,
        spawn_step=lambda task, step, attempt_id: spawned.append(step.step_id) or 999,
        roster_ok=lambda agent_id: True,
    ))
    assert result.action == "review_inserted"
    assert spawned == []  # s2 must NOT have been spawned this tick either
