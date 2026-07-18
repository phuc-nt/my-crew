"""`confirm_amendment`'s TOCTOU re-validate (v13 M34): a draft binds `base_plan_hash`
to the task's FULL-DAG hash at draft time — anything that changes the persisted DAG
between draft and confirm (a pending step finishing, a pending step starting to run, a
ticker-inserted review/rework row landing) must make confirm reject and signal
re-preview, never silently apply a plan against a DAG the CEO never actually saw.
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
        {"step_id": "s2", "title": "B", "assigned_to": "agent-b", "deps": []},
    ]
    store.create_task(task_id=task_id, title="demo task", original_request="lam demo")
    store.set_plan(task_id, steps, plan_hash=_content_hash(steps))


def _draft_over_current_dag(store: TeamTaskStore, task_id: str, new_pending: list[dict]) -> str:
    """Mirror `preview_adjust_team_task`'s own bookkeeping: snapshot the FULL-DAG hash
    and the currently-pending step ids, mint the new plan hash from confirmed+new."""
    task = store.get(task_id)
    base_hash = full_dag_plan_hash(task.steps)
    old_pending_ids = [s.step_id for s in task.steps if s.status == "pending"]
    kept = [s for s in task.steps if s.status != "pending"]
    kept_dicts = [
        {"step_id": s.step_id, "title": s.title, "assigned_to": s.assigned_to, "deps": list(s.deps)}
        for s in kept
    ]
    new_hash = _content_hash(kept_dicts + new_pending)
    return store.set_amendment_draft(
        task_id, base_plan_hash=base_hash, new_plan_hash=new_hash,
        new_pending_steps=new_pending, old_pending_step_ids=old_pending_ids,
    )


def test_pending_step_finishing_before_confirm_rejects_stale_draft(tmp_path):
    """`decomposition_content_hash`/`full_dag_plan_hash` deliberately EXCLUDES `status`
    (see that function's docstring), so a bare `pending -> done` transition on one of
    this draft's own target steps does NOT change `base_plan_hash` — the rejection here
    comes from the `old_pending_step_ids` swap-time check instead (the step is no
    longer `pending` at all), proving the two checks are complementary, not redundant."""
    store = _store(tmp_path)
    _plan(store)
    amendment_id = _draft_over_current_dag(
        store, "t1", [{"step_id": "s3", "title": "C", "assigned_to": "agent-a", "deps": []}],
    )

    # s1 finishes (a completed-prefix change) between draft and confirm.
    store.reserve_step("t1", "s1")
    store.mark_done("t1", "s1", cost_usd=0.1)

    result = store.confirm_amendment("t1", amendment_id)
    assert result.ok is False
    assert result.reason == "pending_step_just_reserved"
    assert result.skipped_step_ids == ("s1",)

    # Rejected confirm leaves the draft re-previewable (still 'draft' status) and the
    # DAG untouched (s1 stays done, s2 stays pending, no swap applied at all).
    draft = store.get_amendment_draft(amendment_id)
    assert draft.status == "draft"
    task = store.get("t1")
    statuses = {s.step_id: s.status for s in task.steps}
    assert statuses == {"s1": "done", "s2": "pending"}


def test_new_review_row_inserted_before_confirm_rejects_via_hash_mismatch(tmp_path):
    """A ticker-inserted row (e.g. a review/rework step landing between draft and
    confirm) DOES change `full_dag_plan_hash` (it hashes every persisted row, not just
    the confirmed subset) — this is the structural-change half of the TOCTOU guard,
    distinct from the narrower pending-status race covered above."""
    store = _store(tmp_path)
    _plan(store)
    amendment_id = _draft_over_current_dag(
        store, "t1", [{"step_id": "s3", "title": "C", "assigned_to": "agent-a", "deps": []}],
    )

    store.insert_step("t1", {
        "step_id": "s1-review-0-0", "title": "Soát chéo: A", "assigned_to": "agent-b",
        "deps": ["s1"], "step_type": "review", "parent_step_id": "s1", "review_round": 0,
    })

    result = store.confirm_amendment("t1", amendment_id)
    assert result.ok is False
    assert result.reason == "plan_changed_since_draft"
    draft = store.get_amendment_draft(amendment_id)
    assert draft.status == "draft"


def test_pending_step_starting_to_run_before_confirm_rejects_stale_draft(tmp_path):
    """A bare pending->running transition does NOT change `decomposition_content_hash`
    (status is deliberately excluded from the hash) — but `full_dag_plan_hash` is not
    what catches this race; `old_pending_step_ids` is. Still, together they must reject."""
    store = _store(tmp_path)
    _plan(store)
    amendment_id = _draft_over_current_dag(
        store, "t1", [{"step_id": "s3", "title": "C", "assigned_to": "agent-a", "deps": []}],
    )

    # s2 (one of the pending steps this draft intends to replace) starts running.
    store.reserve_step("t1", "s2")

    result = store.confirm_amendment("t1", amendment_id)
    assert result.ok is False
    assert result.reason == "pending_step_just_reserved"
    assert result.skipped_step_ids == ("s2",)

    draft = store.get_amendment_draft(amendment_id)
    assert draft.status == "draft"  # still re-confirmable once re-previewed
    task = store.get("t1")
    statuses = {s.step_id: s.status for s in task.steps}
    assert statuses["s2"] == "running"  # untouched by the rejected swap


def test_no_change_since_draft_confirms_cleanly(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    amendment_id = _draft_over_current_dag(
        store, "t1", [{"step_id": "s3", "title": "C", "assigned_to": "agent-a", "deps": []}],
    )
    result = store.confirm_amendment("t1", amendment_id)
    assert result.ok is True
    task = store.get("t1")
    # Both original steps were `pending` at draft time (neither done/running yet), so
    # the swap replaces the WHOLE pending set {s1, s2} with the new pending set {s3}.
    assert {s.step_id for s in task.steps} == {"s3"}
    draft = store.get_amendment_draft(amendment_id)
    assert draft.status == "confirmed"
