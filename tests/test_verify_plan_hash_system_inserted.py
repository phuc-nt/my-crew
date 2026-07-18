"""`coordinator_graph._verify_plan_hash`'s `system_inserted` gate: the recompute must
run ONLY over rows with `system_inserted == 0` (via `getattr(s, "system_inserted", 0)`,
default 0) so a later phase's auto-inserted review/rework row (P2) never falsely stalls
a task's dispatch by moving the recomputed hash away from the CEO-confirmed one.

Two things pinned here:
- forward-compat default: `TeamStep` does not carry a `system_inserted` column yet (P2
  adds it) — `getattr(..., 0)` must default every CURRENT row to 0 (included), so
  today's behavior is the un-gated recompute, unchanged.
- the gate LOGIC itself (exercised directly against `_verify_plan_hash`, not through the
  DB, since the column does not exist yet): a step object carrying `system_inserted=1`
  must be EXCLUDED from the recompute, so inserting such a row does not move the hash.
- end-to-end round-trip: confirm a plan WITH `acceptance` set on a step -> `set_plan`
  persists it to the `acceptance` column -> a normal tick's `_verify_plan_hash` still
  matches (acceptance never entered the hash to begin with) -> no stall.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from my_crew.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker, run_one_tick
from my_crew.agent.task_decomposition import decomposition_content_hash
from my_crew.runtime.team_task_store import TeamTask, TeamTaskStore


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    """Every DB-backed test in this module writes through the shared cross-agent root
    (store, office-room appends) — pin it to tmp_path so no test can touch the real
    install's .data."""
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


def _task(*, steps, plan_hash: str) -> TeamTask:
    """A real `TeamTask` (not a SimpleNamespace) — `_verify_plan_hash` calls
    `dataclasses.replace(task, ...)`, which requires an actual dataclass instance."""
    return TeamTask(
        id="t1", title="demo", original_request="lam demo", status="open",
        created_at="2026-07-10T00:00:00", assigned_by="ceo", cost_usd_total=0.0,
        plan_hash=plan_hash, decompose_cost_usd=0.0, aggregate_cost_usd=0.0,
        escalated_at=None, steps=tuple(steps),
    )


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
        {"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": [],
         "acceptance": "phải có mở đầu và kết luận"},
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


def test_confirmed_plan_with_acceptance_round_trips_through_store_and_tick_verify_passes(tmp_path):
    """`acceptance` was stored on `team_steps.acceptance` at confirm time (`set_plan`)
    — the tick's `_verify_plan_hash` recompute must still match, because
    `decomposition_content_hash` never reads that column on either side."""
    store = _store(tmp_path)
    _plan(store)

    step = store.get_step("t1", "s1")
    assert step.acceptance == "phải có mở đầu và kết luận"

    result = run_one_tick(_deps(store))
    assert result.action == "spawned"  # no stall — hash still matched
    assert store.get("t1").status == "open"


def test_verify_plan_hash_gate_excludes_system_inserted_rows_by_construction():
    """Exercises `_verify_plan_hash`'s gate logic directly against synthetic step
    objects (not via the DB — `TeamStep` has no `system_inserted` column yet, P2 adds
    it): a row with `system_inserted=1` must be excluded from the recompute, so its
    presence never moves the hash away from the CONFIRMED (non-inserted) subset."""
    from my_crew.agent.coordinator_graph import _verify_plan_hash

    confirmed_step = SimpleNamespace(
        step_id="s1", title="draft", assigned_to="agent-a", deps=(), system_inserted=0,
    )
    inserted_review_step = SimpleNamespace(
        step_id="s1-review", title="review (auto)", assigned_to="agent-a", deps=("s1",),
        system_inserted=1,
    )
    confirmed_hash = decomposition_content_hash(SimpleNamespace(steps=[confirmed_step]))

    task = _task(steps=[confirmed_step, inserted_review_step], plan_hash=confirmed_hash)
    deps = SimpleNamespace(store=None, escalate=lambda *a, **k: None)
    # inserted_review_step (system_inserted=1) must be excluded -> recomputed hash still
    # equals confirmed_hash -> _verify_plan_hash returns None (no stall).
    assert _verify_plan_hash(deps, task) is None


def test_verify_plan_hash_gate_defaults_missing_system_inserted_attr_to_zero():
    """Today's `TeamStep` rows (no `system_inserted` column) must behave EXACTLY like
    `system_inserted=0` (included in the recompute) — the un-gated v12 behavior,
    unchanged, until P2 lands the column."""
    from my_crew.agent.coordinator_graph import _verify_plan_hash

    step_without_attr = SimpleNamespace(step_id="s1", title="draft", assigned_to="agent-a", deps=())
    assert not hasattr(step_without_attr, "system_inserted")
    confirmed_hash = decomposition_content_hash(SimpleNamespace(steps=[step_without_attr]))

    task = _task(steps=[step_without_attr], plan_hash=confirmed_hash)
    deps = SimpleNamespace(store=None, escalate=lambda *a, **k: None)
    assert _verify_plan_hash(deps, task) is None


def test_verify_plan_hash_still_stalls_on_a_genuine_confirmed_row_mismatch():
    """The gate must not become a blanket bypass: a mismatch among CONFIRMED
    (system_inserted=0) rows still stalls the task exactly like before."""
    from my_crew.agent.coordinator_graph import _verify_plan_hash

    confirmed_step = SimpleNamespace(
        step_id="s1", title="draft", assigned_to="agent-a", deps=(), system_inserted=0,
    )
    task = _task(steps=[confirmed_step], plan_hash="tampered-hash-value")
    escalated: list[str] = []
    store_calls: list[str] = []
    deps = SimpleNamespace(
        store=SimpleNamespace(set_task_status=lambda tid, status: store_calls.append(status)),
        escalate=lambda t, s, kind, msg: escalated.append(kind),
    )
    result = _verify_plan_hash(deps, task)
    assert result is not None
    assert result.action == "stalled"
    assert escalated == ["plan_hash_mismatch"]
    assert store_calls == ["stalled"]


def test_replace_steps_via_dataclasses_replace_preserves_confirmed_ordering(tmp_path):
    """`_verify_plan_hash` builds `confirmed_task` via `dataclasses.replace(task,
    steps=confirmed_steps)` — `TeamTask` (frozen) must support this, and the filtered
    tuple must preserve the original steps' order (hash is order-sensitive per
    `decomposition_content_hash`'s own contract)."""
    store = _store(tmp_path)
    _plan(store)
    task = store.get("t1")
    confirmed_steps = tuple(s for s in task.steps if getattr(s, "system_inserted", 0) == 0)
    confirmed_task = replace(task, steps=confirmed_steps)
    assert [s.step_id for s in confirmed_task.steps] == [s.step_id for s in task.steps]
    assert decomposition_content_hash(confirmed_task) == task.plan_hash
