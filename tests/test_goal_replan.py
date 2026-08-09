"""v75 phase 2: goal-directed replan — autopilot rung 2 changes the PLAN, fail-closed.

The amend LLM is stubbed (`amend_with_retries`); everything below it is real: store,
amendment draft, hash-guarded confirm, reopen, office milestone.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from my_crew.agent.task_decomposition import decomposition_content_hash
from my_crew.runtime.goal_replan import run_goal_replan
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    return tmp_path


def _open_store():
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    return TeamTaskStore(team_tasks_db_path())


def _hash(steps: list[dict]) -> str:
    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(step_id=s["step_id"], title=s["title"],
                        assigned_to=s["assigned_to"], deps=tuple(s.get("deps", ())))
        for s in steps
    ]))


_PLAN = [
    {"step_id": "s1", "title": "thu thập", "assigned_to": "agent-a", "deps": []},
    {"step_id": "s2", "title": "tổng hợp", "assigned_to": "agent-b", "deps": ["s1"]},
]


def _mk_stalled_with_dead_step(task_id="t1"):
    store = _open_store()
    try:
        store.create_task(task_id=task_id, title="Demo", original_request="x",
                          assigned_by="ceo")
        store.set_plan(task_id, _PLAN, _hash(_PLAN))
        attempt = store.reserve_step(task_id, "s1")
        store.mark_failed(task_id, "s1", attempt_id=attempt)
        store.set_task_status(task_id, "stalled")
    finally:
        store.close()


def _patch_amend(monkeypatch, new_pending):
    """Stub the ONLY LLM call: returns `new_pending` + a combined task for the hash."""
    def _fake(task, request, staff):
        frozen = [s for s in task.steps if s.status != "pending"]
        combined = SimpleNamespace(steps=[
            *[SimpleNamespace(step_id=s.step_id, title=s.title,
                              assigned_to=s.assigned_to, deps=tuple(s.deps))
              for s in frozen],
            *[SimpleNamespace(step_id=d["step_id"], title=d["title"],
                              assigned_to=d["assigned_to"],
                              deps=tuple(d.get("deps", ())))
              for d in new_pending],
        ])
        return new_pending, combined, 0.001

    monkeypatch.setattr("my_crew.agent.team_task_amend_prompt.amend_with_retries", _fake)
    monkeypatch.setattr("my_crew.agent.team_task_roster.assignable_staff",
                        lambda: [("agent-a", "office"), ("agent-b", "office")])


def test_replan_applies_a_changed_pending_tail_and_reopens(monkeypatch):
    _mk_stalled_with_dead_step()
    _patch_amend(monkeypatch, [
        {"step_id": "s2b", "title": "tổng hợp theo cách khác", "assigned_to": "agent-a",
         "deps": []},
    ])
    reply = run_goal_replan({"task_id": "t1"})
    assert "cách tiếp cận" in reply
    store = _open_store()
    try:
        task = store.get("t1")
        assert task.status == "open"
        ids = {s.step_id for s in task.steps}
        assert "s2b" in ids and "s2" not in ids  # pending tail swapped
    finally:
        store.close()


def test_replan_refuses_identity_proposal(monkeypatch):
    _mk_stalled_with_dead_step()
    _patch_amend(monkeypatch, [
        {"step_id": "s2", "title": "tổng hợp", "assigned_to": "agent-b", "deps": ["s1"]},
    ])
    with pytest.raises(ValueError, match="không thay đổi"):
        run_goal_replan({"task_id": "t1"})
    store = _open_store()
    try:
        assert store.get("t1").status == "stalled"  # fail-closed: stall stands
    finally:
        store.close()


def test_replan_refuses_when_no_pending_tail(monkeypatch):
    store = _open_store()
    try:
        store.create_task(task_id="t2", title="Demo2", original_request="x",
                          assigned_by="ceo")
        one = [{"step_id": "s1", "title": "a", "assigned_to": "agent-a", "deps": []}]
        store.set_plan("t2", one, _hash(one))
        attempt = store.reserve_step("t2", "s1")
        store.mark_failed("t2", "s1", attempt_id=attempt)
        store.set_task_status("t2", "stalled")
    finally:
        store.close()
    with pytest.raises(ValueError, match="không còn bước chờ"):
        run_goal_replan({"task_id": "t2"})


def test_replan_wraps_amend_failure_as_refusal(monkeypatch):
    from my_crew.agent.task_decomposition import DecompositionError

    _mk_stalled_with_dead_step()

    def _boom(task, request, staff):
        raise DecompositionError("model chịu")

    monkeypatch.setattr("my_crew.agent.team_task_amend_prompt.amend_with_retries", _boom)
    monkeypatch.setattr("my_crew.agent.team_task_roster.assignable_staff",
                        lambda: [("agent-a", "office")])
    with pytest.raises(ValueError, match="không soạn được"):
        run_goal_replan({"task_id": "t1"})
