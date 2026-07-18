"""Amend confirm swaps ONLY `pending` steps (v13 M34): `done`/`running`/`failed` steps
are structurally untouched by a confirmed amendment — the DAG's completed/in-flight
prefix is immutable through a replan, only the yet-to-run tail can change. Also covers
`new_plan_hash` binding and draft consumption/cancellation.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from my_crew.agent.task_decomposition import decomposition_content_hash
from my_crew.runtime.team_task_amend import full_dag_plan_hash
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


def _store(tmp_path) -> TeamTaskStore:
    return TeamTaskStore(tmp_path / "team_tasks.sqlite3")


def _content_hash(steps: list[dict]) -> str:
    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(
            step_id=s["step_id"], title=s["title"], assigned_to=s["assigned_to"],
            deps=tuple(s.get("deps", ())),
        )
        for s in steps
    ]))


def _plan(store: TeamTaskStore, task_id="t1") -> None:
    steps = [
        {"step_id": "s1", "title": "done work", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s2", "title": "running work", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s3", "title": "failed work", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s4", "title": "pending A", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s5", "title": "pending B", "assigned_to": "agent-b", "deps": []},
    ]
    store.create_task(task_id=task_id, title="demo task", original_request="lam demo")
    store.set_plan(task_id, steps, plan_hash=_content_hash(steps))
    store.reserve_step(task_id, "s1")
    store.mark_done(task_id, "s1", cost_usd=0.1)
    store.reserve_step(task_id, "s2")  # left running
    store.reserve_step(task_id, "s3")
    store.mark_failed(task_id, "s3")


def _draft_replacing_pending(store: TeamTaskStore, task_id: str, new_pending: list[dict]) -> str:
    task = store.get(task_id)
    base_hash = full_dag_plan_hash(task.steps)
    old_pending_ids = [s.step_id for s in task.steps if s.status == "pending"]
    return store.set_amendment_draft(
        task_id, base_plan_hash=base_hash,
        new_plan_hash=_content_hash([
            {"step_id": s.step_id, "title": s.title, "assigned_to": s.assigned_to,
             "deps": list(s.deps)}
            for s in task.steps if s.status != "pending"
        ] + new_pending),
        new_pending_steps=new_pending, old_pending_step_ids=old_pending_ids,
    )


def test_confirmed_swap_leaves_done_running_failed_untouched(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    new_pending = [{"step_id": "s6", "title": "pending C", "assigned_to": "agent-a", "deps": []}]
    amendment_id = _draft_replacing_pending(store, "t1", new_pending)

    result = store.confirm_amendment("t1", amendment_id)
    assert result.ok is True

    task = store.get("t1")
    by_id = {s.step_id: s for s in task.steps}
    assert set(by_id) == {"s1", "s2", "s3", "s6"}  # s4/s5 swapped away, s6 added
    assert by_id["s1"].status == "done"
    assert by_id["s2"].status == "running"
    assert by_id["s3"].status == "failed"
    assert by_id["s6"].status == "pending"


def test_confirmed_swap_binds_new_plan_hash(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    new_pending = [{"step_id": "s6", "title": "pending C", "assigned_to": "agent-a", "deps": []}]
    amendment_id = _draft_replacing_pending(store, "t1", new_pending)
    draft = store.get_amendment_draft(amendment_id)

    result = store.confirm_amendment("t1", amendment_id)
    assert result.ok is True
    task = store.get("t1")
    assert task.plan_hash == draft.new_plan_hash


def test_confirm_consumes_the_draft(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    new_pending = [{"step_id": "s6", "title": "pending C", "assigned_to": "agent-a", "deps": []}]
    amendment_id = _draft_replacing_pending(store, "t1", new_pending)

    store.confirm_amendment("t1", amendment_id)
    draft = store.get_amendment_draft(amendment_id)
    assert draft.status == "confirmed"

    # A second confirm attempt against the now-consumed draft is a clean no-op reject.
    result = store.confirm_amendment("t1", amendment_id)
    assert result.ok is False
    assert result.reason == "amendment_not_live"


def test_cancel_draft_terminalizes_it_before_any_confirm(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    new_pending = [{"step_id": "s6", "title": "pending C", "assigned_to": "agent-a", "deps": []}]
    amendment_id = _draft_replacing_pending(store, "t1", new_pending)

    cancelled = store.cancel_amendment_draft(amendment_id)
    assert cancelled is True
    draft = store.get_amendment_draft(amendment_id)
    assert draft.status == "cancelled"

    result = store.confirm_amendment("t1", amendment_id)
    assert result.ok is False
    assert result.reason == "amendment_not_live"
    task = store.get("t1")
    assert {s.step_id for s in task.steps} == {"s1", "s2", "s3", "s4", "s5"}  # unchanged


def test_cancel_an_already_confirmed_draft_is_a_safe_no_op(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    new_pending = [{"step_id": "s6", "title": "pending C", "assigned_to": "agent-a", "deps": []}]
    amendment_id = _draft_replacing_pending(store, "t1", new_pending)
    store.confirm_amendment("t1", amendment_id)

    cancelled = store.cancel_amendment_draft(amendment_id)
    assert cancelled is False  # already terminal (confirmed), nothing to cancel
    draft = store.get_amendment_draft(amendment_id)
    assert draft.status == "confirmed"  # unchanged, not flipped to cancelled
