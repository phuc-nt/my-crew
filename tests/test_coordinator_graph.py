"""Coordinator ticker orchestration (v12 M28b): reserve/spawn, poll/retry/timeout,
aggregate/deliver, cost cap, reboot recovery — all against `run_one_tick` with fully
injectable doubles (no real subprocess/network/LLM/clock).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from my_crew.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker, run_one_tick
from my_crew.agent.task_decomposition import decomposition_content_hash
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    """Every test in this module writes through the shared cross-agent root (store,
    artifacts, office-room appends) — pin it to tmp_path so no test can touch the
    real install's .data (the office room is a real user-visible surface)."""
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)

def _store(tmp_path, **kw) -> TeamTaskStore:
    return TeamTaskStore(tmp_path / "team_tasks.sqlite3", **kw)


def _content_hash(steps: list[dict]) -> str:
    """The REAL dispatch-time hash for a given step-dict list — the ticker's
    `_verify_plan_hash` recomputes this on every tick, so fixtures must
    persist the matching hash, not an arbitrary literal, or every tick would stall."""
    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(
            step_id=s["step_id"], title=s["title"], assigned_to=s["assigned_to"],
            deps=tuple(s.get("deps", ())),
        )
        for s in steps
    ]))


def _plan(store: TeamTaskStore, task_id="t1", steps=None) -> None:
    steps = steps or [
        {"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s2", "title": "review", "assigned_to": "agent-b", "deps": ["s1"]},
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


# --- no open tasks / nothing actionable ---------------------------------------------


def test_no_open_tasks_is_a_clean_none(tmp_path):
    store = _store(tmp_path)
    result = run_one_tick(_deps(store))
    assert result.action == "none"
    assert result.task_id is None


# --- reserve + spawn (detached, not waited) -----------------------------------------


def test_pending_step_reserves_lease_and_spawns_detached(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    spawned = []

    def _spawn(task, step, attempt_id):
        spawned.append((task.id, step.step_id, attempt_id))
        return 999

    result = run_one_tick(_deps(store, spawn_step=_spawn))
    assert result.action == "spawned"
    assert len(spawned) == 1
    task_id, step_id, attempt_id = spawned[0]
    assert task_id == "t1" and step_id == "s1"

    # The store now shows the step running with the reserved lease + recorded pid —
    # spawn_step was never waited on (this test itself proves that: it returned
    # synchronously without blocking).
    step = store.get_step("t1", "s1")
    assert step.status == "running"
    assert step.child_pid == 999


def test_dispatch_time_roster_check_rejects_unauthorized_assignee_no_spawn(tmp_path):
    """A step's `assigned_to` was authorized at decompose time, but the
    registry can drift before dispatch. `roster_ok` returning False must fail the step
    + escalate WITHOUT ever calling `reserve_step`/`spawn_step` — the identity is no
    longer trusted to run anything."""
    store = _store(tmp_path)
    _plan(store)
    spawned = []
    escalated = []

    result = run_one_tick(_deps(
        store,
        spawn_step=lambda task, step, attempt_id: spawned.append(step.step_id) or 999,
        roster_ok=lambda agent_id: agent_id != "agent-a",
        escalate=lambda task, step, kind, msg: escalated.append(kind),
    ))
    assert result.action == "failed"
    assert spawned == []
    assert escalated == ["step_assignee_unauthorized"]

    step = store.get_step("t1", "s1")
    assert step.status == "failed"
    assert step.child_pid is None  # never reserved/spawned


def test_dispatch_read_plan_hash_mismatch_stalls_task_no_dispatch(tmp_path):
    """The ticker recomputes the plan's content hash on every tick and compares
    against the stored `plan_hash` BEFORE any dispatch action. A mismatch (on-disk steps
    no longer match what `confirm_plan` bound the CEO's approval to) must stall the task
    + escalate, never spawn a step from an unverified DAG."""
    store = _store(tmp_path)
    _plan(store)
    # Corrupt the stored plan_hash directly (simulates a tampered/out-of-band write —
    # `set_plan`/`confirm_plan` themselves always keep hash and steps in sync).
    store._conn.execute("UPDATE team_tasks SET plan_hash = 'tampered' WHERE id = 't1'")
    store._conn.commit()

    spawned = []
    escalated = []
    result = run_one_tick(_deps(
        store,
        spawn_step=lambda task, step, attempt_id: spawned.append(step.step_id) or 999,
        escalate=lambda task, step, kind, msg: escalated.append(kind),
    ))
    assert result.action == "stalled"
    assert spawned == []
    assert escalated == ["plan_hash_mismatch"]
    assert store.get("t1").status == "stalled"


def test_dispatch_read_plan_hash_match_proceeds_normally(tmp_path):
    """The common case: `_plan`'s fixture hash matches the real recomputed hash, so the
    check is a silent no-op and dispatch proceeds exactly as before."""
    store = _store(tmp_path)
    _plan(store)
    result = run_one_tick(_deps(store))
    assert result.action == "spawned"


def test_dispatch_time_roster_check_allows_authorized_assignee(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    spawned = []

    result = run_one_tick(_deps(
        store,
        spawn_step=lambda task, step, attempt_id: spawned.append(step.step_id) or 999,
        roster_ok=lambda agent_id: True,
    ))
    assert result.action == "spawned"
    assert spawned == ["s1"]


def test_dependent_step_not_ready_until_dep_done(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    result = run_one_tick(_deps(store))
    assert result.action == "spawned"
    assert result.detail.startswith("s1")  # s2 is blocked on s1, s1 is the only ready step


# --- poll running step: dead pid ------------------------------------------------------


def test_dead_pid_no_artifact_retries_once_then_spawns_again(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    attempt_id = store.reserve_step("t1", "s1")
    store.record_spawn("t1", "s1", 111)

    result = run_one_tick(_deps(store, pid_alive=lambda pid: False))
    assert result.action == "spawned"  # retry-driven respawn surfaces as "spawned"

    step = store.get_step("t1", "s1")
    assert step.status == "running"
    assert step.attempt_id != attempt_id  # a FRESH lease was issued on the retry


def test_dead_pid_second_time_marks_failed_and_escalates(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    store.reserve_step("t1", "s1")
    store.record_spawn("t1", "s1", 111)
    escalated = []

    deps = _deps(store, pid_alive=lambda pid: False,
                 escalate=lambda task, step, kind, msg: escalated.append((kind, step.step_id)))
    # First tick: retry (re-spawns).
    run_one_tick(deps)
    # Second tick: the SAME dead-pid condition persists (test double keeps returning
    # pid_alive=False) — retries exhausted -> failed + escalate.
    result = run_one_tick(deps)

    assert result.action == "failed"
    assert store.get_step("t1", "s1").status == "failed"
    assert escalated == [("step_failed", "s1")]


# --- poll running step: lease timeout ------------------------------------------------


def test_lease_expired_kills_pid_marks_timeout_and_escalates(tmp_path):
    store = _store(tmp_path, lease_ttl_s=60)
    _plan(store)
    store.reserve_step("t1", "s1")
    store.record_spawn("t1", "s1", 555)
    killed = []
    escalated = []

    # now() is far past the lease TTL, but pid_alive=True (still running, just stuck) —
    # this is the timeout branch, distinct from the dead-pid/retry branch above.
    future = datetime.now(UTC) + timedelta(seconds=120)
    deps = _deps(
        store, pid_alive=lambda pid: True,
        kill_pid=lambda pid, attempt_id: killed.append((pid, attempt_id)),
        escalate=lambda task, step, kind, msg: escalated.append((kind, step.step_id)),
        now=lambda: future,
    )
    result = run_one_tick(deps)

    assert result.action == "timeout_escalated"
    assert len(killed) == 1 and killed[0][0] == 555
    assert store.get_step("t1", "s1").status == "timeout"
    assert escalated == [("step_timeout", "s1")]


def test_lease_clock_paused_for_awaiting_approval_step(tmp_path):
    """An `awaiting_approval` step is never polled — its lease clock is effectively
    PAUSED by construction (only `running` steps are inspected)."""
    store = _store(tmp_path)
    _plan(store, steps=[{"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []}])
    store.reserve_step("t1", "s1")
    store.mark_awaiting_approval("t1", "s1")

    future = datetime.now(UTC) + timedelta(hours=999)
    result = run_one_tick(_deps(store, now=lambda: future))
    # Nothing to poll (not `running`), nothing pending (only step is awaiting_approval,
    # not done) -> "none", the step untouched.
    assert result.action == "none"
    assert store.get_step("t1", "s1").status == "awaiting_approval"


# --- task-lifecycle dead-end: a failed/timeout step with no retry left --------------


def test_failed_step_with_no_other_actionable_step_stalls_task_and_escalates_once(tmp_path):
    """A single-step task whose only step exhausts retries and lands `failed` must not
    sit `open` forever (never all-done, never re-dispatchable) — the task itself needs
    a terminal `stalled` + a one-time escalation."""
    store = _store(tmp_path)
    _plan(store, steps=[{"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []}])
    store.reserve_step("t1", "s1")
    store.mark_failed("t1", "s1")
    escalated = []

    deps = _deps(store, escalate=lambda task, step, kind, msg: escalated.append((kind, step)))
    result = run_one_tick(deps)

    assert result.action == "stalled"
    assert store.get("t1").status == "stalled"
    assert escalated == [("task_stalled_dead_step", None)]

    # Second tick: the task is no longer dispatchable at all (stalled is not in
    # list_dispatchable's open/running set) -> "exactly once" is enforced structurally,
    # not by a flag — a second tick sees no open tasks, escalate is never called again.
    result2 = run_one_tick(deps)
    assert result2.action == "none"
    assert escalated == [("task_stalled_dead_step", None)]


def test_timeout_step_with_no_other_actionable_step_stalls_task(tmp_path):
    store = _store(tmp_path)
    _plan(store, steps=[{"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []}])
    store.reserve_step("t1", "s1")
    store.mark_timeout("t1", "s1")

    result = run_one_tick(_deps(store))
    assert result.action == "stalled"
    assert store.get("t1").status == "stalled"


def test_failed_step_does_not_stall_task_while_a_sibling_step_is_still_running(tmp_path):
    """A dead-end for one step must not preempt still-live work on ANOTHER step in the
    same task — the running step is polled/handled first; only once nothing else is
    actionable does the dead-end check fire."""
    store = _store(tmp_path)
    _plan(store, steps=[
        {"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s2", "title": "research", "assigned_to": "agent-b", "deps": []},
    ])
    store.reserve_step("t1", "s1")
    store.mark_failed("t1", "s1")
    store.reserve_step("t1", "s2")
    store.record_spawn("t1", "s2", 4242)

    # s2 is alive and within its lease -> nothing to poll -> "none", task NOT stalled
    # even though s1 is already dead-ended (s2 might still complete this tick's peers).
    result = run_one_tick(_deps(store, pid_alive=lambda pid: True))
    assert result.action == "none"
    assert store.get("t1").status in ("open", "running")


# --- aggregate on all-done -------------------------------------------------------------


def test_all_steps_done_aggregates_delivers_and_marks_task_done(tmp_path):
    store = _store(tmp_path)
    _plan(store, steps=[{"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []}])
    store.reserve_step("t1", "s1")
    store.mark_done("t1", "s1", cost_usd=0.02)
    delivered = []

    result = run_one_tick(_deps(
        store, aggregate=lambda task: ("tong ket", 0.05),
        deliver_room=lambda task, summary: delivered.append((task.id, summary)),
    ))

    assert result.action == "aggregated"
    assert delivered == [("t1", "tong ket")]
    task = store.get("t1")
    assert task.status == "done"
    assert task.aggregate_cost_usd == 0.05


# --- cost cap ----------------------------------------------------------------------


def test_cost_cap_exceeded_stalls_task_and_escalates(tmp_path):
    store = _store(tmp_path)
    _plan(store, steps=[{"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []}])
    store.reserve_step("t1", "s1")
    store.mark_done("t1", "s1", cost_usd=5.0)  # already over the $2 cap
    escalated = []

    result = run_one_tick(_deps(
        store, cost_cap_usd=2.0,
        escalate=lambda task, step, kind, msg: escalated.append(kind),
    ))

    assert result.action == "cap_exceeded"
    assert store.get("t1").status == "stalled"
    assert escalated == ["cost_cap_exceeded"]


def test_cost_cap_checked_before_any_spawn(tmp_path):
    """A task already over cap must never spawn a new step, even if one is ready."""
    store = _store(tmp_path)
    _plan(store)  # s1 pending, s2 depends on s1
    store.record_task_cost("t1", decompose=3.0)  # over the $2 cap before any step ran
    spawned = []

    result = run_one_tick(_deps(
        store, cost_cap_usd=2.0, spawn_step=lambda *a: spawned.append(a) or 1,
    ))

    assert result.action == "cap_exceeded"
    assert spawned == []


# --- reboot recovery -----------------------------------------------------------------


def test_reboot_recovery_fresh_ticker_resumes_from_store(tmp_path):
    """No separate resume trigger: a FRESH CoordinatorDeps/retry-tracker (simulating a
    new OS process after a crash/restart) just re-reads the store and continues."""
    store = _store(tmp_path)
    _plan(store, steps=[{"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []}])
    store.reserve_step("t1", "s1")
    store.record_spawn("t1", "s1", 777)

    # Simulate: the worker process that ran s1 crashed (pid dead) before writing an
    # artifact, and the whole SERVICE also restarted (fresh in-memory retry tracker).
    fresh_deps = _deps(store, pid_alive=lambda pid: False,
                       retry_tracker=in_memory_retry_tracker())
    result = run_one_tick(fresh_deps)

    assert result.action == "spawned"  # retried from a totally fresh process, no crash
    assert store.get_step("t1", "s1").status == "running"


# --- multi-task selection --------------------------------------------------------------


def test_first_actionable_task_wins_when_earlier_task_has_nothing_to_do(tmp_path):
    store = _store(tmp_path)
    # t1: single step already awaiting_approval -> nothing actionable this tick.
    _plan(store, task_id="t1",
          steps=[{"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []}])
    store.reserve_step("t1", "s1")
    store.mark_awaiting_approval("t1", "s1")
    # t2: a pending step ready to go.
    _plan(store, task_id="t2",
          steps=[{"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []}])

    result = run_one_tick(_deps(store))
    assert result.action == "spawned"
    assert result.task_id == "t2"


# --- confirm-bypass invariant: a `planning` draft is tick-invisible to the ticker ---


def test_planning_draft_never_confirmed_is_invisible_to_the_ticker_across_many_ticks(tmp_path):
    """The highest-severity invariant in the team-task design: `preview_assign_team_task`
    persists a DRAFT plan via `set_draft_plan` while the task stays `planning` — ONLY
    `confirm_plan` (the CEO's explicit "xác nhận") may flip it to `open`/dispatchable.
    A regression that re-adds `planning` to the ticker's dispatch set (or a future caller
    reaching for `list_open` instead of `list_dispatchable`) would silently reopen the
    confirm-bypass: the ticker would spawn work the CEO never approved. This test uses
    the REAL preview-time call (`set_draft_plan`, no confirm) — not `set_plan`'s
    test-convenience auto-open — so it fails loud if that bypass is ever reintroduced."""
    steps = [{"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []}]
    store = _store(tmp_path)
    store.create_task(task_id="t1", title="demo task", original_request="lam demo")
    store.set_draft_plan("t1", steps, plan_hash=_content_hash(steps))

    spawned: list = []
    deps = _deps(store, spawn_step=lambda task, step, attempt_id: spawned.append(1) or 999)

    for _ in range(5):
        result = run_one_tick(deps)
        assert result.action == "none"
        assert result.task_id is None

    assert spawned == []
    assert store.get("t1").status == "planning"


def test_cancelled_task_is_also_invisible_to_the_ticker(tmp_path):
    """A drafted-then-cancelled task (CEO said "huỷ") must stay permanently tick-invisible
    — `cancel_draft` terminalizes it to `cancelled`, which is neither in
    `_DISPATCHABLE_TASK_STATUSES` nor re-enterable."""
    steps = [{"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []}]
    store = _store(tmp_path)
    store.create_task(task_id="t1", title="demo task", original_request="lam demo")
    store.set_draft_plan("t1", steps, plan_hash=_content_hash(steps))
    assert store.cancel_draft("t1") is True

    spawned: list = []

    def _spawn(task, step, attempt_id):
        spawned.append(1)
        return 999

    result = run_one_tick(_deps(store, spawn_step=_spawn))

    assert result.action == "none"
    assert spawned == []
    assert store.get("t1").status == "cancelled"
