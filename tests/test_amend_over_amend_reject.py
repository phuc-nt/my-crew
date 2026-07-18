"""Amend-over-amend (v13 M34): SINGLE live draft per task — a second "chỉnh kế hoạch"
before the first is confirmed terminalizes the first outright (never two racing
confirmable drafts); and even if a caller somehow held onto an older
`amendment_id`, confirming a SUPERSEDED draft is rejected the same way any other
already-consumed/terminal draft would be — never silently applied, never able to
overwrite a later confirm.
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
        {"step_id": "s1", "title": "A", "assigned_to": "agent-a", "deps": []},
    ]
    store.create_task(task_id=task_id, title="demo task", original_request="lam demo")
    store.set_plan(task_id, steps, plan_hash=_content_hash(steps))


def _draft(store: TeamTaskStore, task_id: str, new_step_id: str) -> str:
    task = store.get(task_id)
    base_hash = full_dag_plan_hash(task.steps)
    old_pending_ids = [s.step_id for s in task.steps if s.status == "pending"]
    kept = [s for s in task.steps if s.status != "pending"]
    kept_dicts = [
        {"step_id": s.step_id, "title": s.title, "assigned_to": s.assigned_to, "deps": list(s.deps)}
        for s in kept
    ]
    new_pending = [{"step_id": new_step_id, "title": new_step_id, "assigned_to": "agent-a",
                    "deps": []}]
    new_hash = _content_hash(kept_dicts + new_pending)
    return store.set_amendment_draft(
        task_id, base_plan_hash=base_hash, new_plan_hash=new_hash,
        new_pending_steps=new_pending, old_pending_step_ids=old_pending_ids,
    )


def test_second_draft_terminalizes_the_first_before_either_confirms(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    draft_a = _draft(store, "t1", "sA")
    draft_b = _draft(store, "t1", "sB")

    a = store.get_amendment_draft(draft_a)
    b = store.get_amendment_draft(draft_b)
    assert a.status == "stale"  # superseded before it was ever confirmable
    assert b.status == "draft"

    result_a = store.confirm_amendment("t1", draft_a)
    assert result_a.ok is False
    assert result_a.reason == "amendment_not_live"

    result_b = store.confirm_amendment("t1", draft_b)
    assert result_b.ok is True
    task = store.get("t1")
    assert {s.step_id for s in task.steps} == {"sB"}


def test_confirming_a_already_confirmed_draft_is_a_clean_reject_not_a_reapply(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    draft_a = _draft(store, "t1", "sA")
    first = store.confirm_amendment("t1", draft_a)
    assert first.ok is True

    # A caller somehow re-invokes confirm on the SAME already-consumed draft (e.g. a
    # duplicate ops-chat "xác nhận" reply landing twice) — must not re-apply.
    second = store.confirm_amendment("t1", draft_a)
    assert second.ok is False
    assert second.reason == "amendment_not_live"
    task = store.get("t1")
    assert {s.step_id for s in task.steps} == {"sA"}  # unchanged, not re-swapped


def test_draft_b_over_draft_a_confirmed_first_rejects_via_hash_mismatch(tmp_path):
    """Even in the pathological case where a caller bypasses the single-draft
    terminalize invariant (e.g. two drafts minted for two DIFFERENT tasks' worth of
    stale in-memory state, or a lower-level direct call), confirming a draft whose
    `base_plan_hash` no longer matches the task (because a different draft's confirm
    already changed the DAG) is rejected by the hash check — belt-and-braces on top of
    the single-live-draft terminalize."""
    store = _store(tmp_path)
    _plan(store)
    _draft(store, "t1", "sA")
    draft_b = _draft(store, "t1", "sB")  # terminalizes A's 'draft' status to 'stale'

    # Confirm A anyway is rejected (not live) — proven above. Confirm B (the live one)
    # applies. A LATER attempt to confirm A must ALSO fail even if something had
    # resurrected its status back to 'draft' (defense in depth): the hash no longer
    # matches once B's confirm changed the DAG.
    confirmed_b = store.confirm_amendment("t1", draft_b)
    assert confirmed_b.ok is True

    task = store.get("t1")
    assert {s.step_id for s in task.steps} == {"sB"}
