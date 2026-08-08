"""An amendment's new pending steps may depend on FROZEN (done/running) steps.

A step only reads its direct deps' artifacts — data does not flow transitively — so a
replan that cannot point a new step at a completed producer loses that producer's data
forever (observed live: a mid-task amend to widen `finalize`'s deps was rejected with
"depends on unknown step(s) ['outline']" because the parse validated the new slice
alone). Deps on a FAILED step stay rejected: its artifact never comes, so dispatch
would deadlock.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from my_crew.agent.task_decomposition import DecompositionError
from my_crew.agent.team_task_amend_prompt import amend_with_retries


def _task():
    def step(step_id, status, deps=()):
        return SimpleNamespace(
            step_id=step_id, title=f"bước {step_id}", assigned_to="agent-a",
            deps=tuple(deps), status=status, system_inserted=0,
            needs_shell=False, external_write=False,
        )

    return SimpleNamespace(
        id="t1", pic_id="",
        steps=[
            step("research", "done"),
            step("outline", "running", deps=("research",)),
            step("s3", "failed"),
            step("draft", "pending", deps=("outline",)),
        ],
    )


def _wire_llm(monkeypatch, completion: dict):
    class _Result:
        content = json.dumps(completion)
        cost_usd = 0.001

    class _Llm:
        def complete(self, _messages):
            return _Result()

    monkeypatch.setattr(
        "my_crew.agent.team_task_amend_prompt._build_llm", lambda: (_Llm(), None)
    )


def test_new_pending_step_may_depend_on_done_and_running_steps(monkeypatch):
    _wire_llm(monkeypatch, {"steps": [
        {"step_id": "draft", "title": "viết nháp", "assigned_to": "agent-a",
         "deps": ["research", "outline"]},
    ]})
    new_pending, combined, _cost = amend_with_retries(
        _task(), "draft cần đọc cả research", [("agent-a", "pm")],
    )
    assert new_pending[0]["deps"] == ["research", "outline"]
    assert {s.step_id for s in combined.steps} == {"research", "outline", "s3", "draft"}


def test_dep_on_a_failed_step_is_rejected(monkeypatch):
    """A failed step's artifact never arrives — depending on it deadlocks dispatch."""
    _wire_llm(monkeypatch, {"steps": [
        {"step_id": "draft", "title": "viết nháp", "assigned_to": "agent-a",
         "deps": ["s3"]},
    ]})
    with pytest.raises(DecompositionError, match="s3"):
        amend_with_retries(_task(), "x", [("agent-a", "pm")])


def test_dep_on_a_truly_unknown_id_is_still_rejected(monkeypatch):
    _wire_llm(monkeypatch, {"steps": [
        {"step_id": "draft", "title": "viết nháp", "assigned_to": "agent-a",
         "deps": ["ghost"]},
    ]})
    with pytest.raises(DecompositionError, match="ghost"):
        amend_with_retries(_task(), "x", [("agent-a", "pm")])
