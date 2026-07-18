"""M32 review-insert ticker rule (`coordinator_nodes.review_insert`): a `done` `work`
step with `needs_review=True` mints a review-step child; a `done` `review` step's
verdict drives rework-insert / stall-escalate; a `done` `rework` step mints the next
review round. Exercised directly against the pure functions with a real
`TeamTaskStore` (SQLite) + a fake `CoordinatorDeps`, mirroring `test_coordinator_graph
.py`'s fixture style.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import my_crew.agent.team_task_roster as roster_mod
from my_crew.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker
from my_crew.agent.coordinator_nodes.review_insert import (
    MAX_REVIEW_ROUNDS,
    maybe_handle_review_done,
    maybe_insert_review,
    maybe_insert_review_after_rework,
)
from my_crew.agent.task_decomposition import decomposition_content_hash
from my_crew.agent.team_task_artifact import write_review_verdict_artifact
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


def _store(tmp_path) -> TeamTaskStore:
    return TeamTaskStore(tmp_path / "team_tasks.sqlite3")


def _content_hash(steps: list[dict]) -> str:
    from types import SimpleNamespace

    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(
            step_id=s["step_id"], title=s["title"], assigned_to=s["assigned_to"],
            deps=tuple(s.get("deps", ())),
        )
        for s in steps
    ]))


def _plan_one_step(store: TeamTaskStore, *, needs_review: bool = True, task_id="t1") -> None:
    steps = [
        {"step_id": "s1", "title": "draft báo cáo", "assigned_to": "agent-a", "deps": [],
         "needs_review": needs_review},
    ]
    store.create_task(task_id=task_id, title="demo task", original_request="lam demo")
    store.set_plan(task_id, steps, plan_hash=_content_hash(steps))
    store.mark_done(task_id, "s1", outcome_ref="x", cost_usd=0.0)


def _deps(store, **overrides) -> CoordinatorDeps:
    base = dict(
        store=store, retry_tracker=in_memory_retry_tracker(), cost_cap_usd=2.0,
        escalate=lambda task, step, kind, msg: None, now=lambda: datetime.now(UTC),
    )
    base.update(overrides)
    return CoordinatorDeps(**base)


def _wire_roster(monkeypatch, roster: list[tuple[str, str]]) -> None:
    monkeypatch.setattr(roster_mod, "assignable_staff", lambda: roster)


# --- rule 1: work -> review insert ---------------------------------------------------


def test_work_step_done_with_needs_review_mints_review_child(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _wire_roster(monkeypatch, [("agent-a", "pm"), ("agent-qa", "pm")])
    task = store.get("t1")
    done_step = next(s for s in task.steps if s.step_id == "s1")

    inserted = maybe_insert_review(_deps(store), task, done_step)
    assert inserted is True

    task = store.get("t1")
    review_steps = [s for s in task.steps if s.step_type == "review"]
    assert len(review_steps) == 1
    review = review_steps[0]
    assert review.assigned_to == "agent-qa"
    assert review.parent_step_id == "s1"
    assert review.review_round == 0
    assert review.system_inserted is True
    assert review.needs_review is False


def test_work_step_without_needs_review_never_mints_review(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=False)
    _wire_roster(monkeypatch, [("agent-a", "pm"), ("agent-qa", "pm")])
    task = store.get("t1")
    done_step = next(s for s in task.steps if s.step_id == "s1")

    assert maybe_insert_review(_deps(store), task, done_step) is False
    task = store.get("t1")
    assert not [s for s in task.steps if s.step_type == "review"]


def test_review_insert_is_idempotent_no_double_mint(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _wire_roster(monkeypatch, [("agent-a", "pm"), ("agent-qa", "pm")])
    task = store.get("t1")
    done_step = next(s for s in task.steps if s.step_id == "s1")
    maybe_insert_review(_deps(store), task, done_step)

    task = store.get("t1")
    done_step = next(s for s in task.steps if s.step_id == "s1")
    assert maybe_insert_review(_deps(store), task, done_step) is False
    task = store.get("t1")
    assert len([s for s in task.steps if s.step_type == "review"]) == 1


def test_no_eligible_reviewer_skips_without_stalling(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _wire_roster(monkeypatch, [("agent-a", "pm")])  # only the author — no peer
    events = []
    monkeypatch.setattr(
        "my_crew.agent.coordinator_nodes.review_insert.append_office_event",
        lambda *a, **kw: events.append(kw.get("body", {}).get("milestone")),
    )
    task = store.get("t1")
    done_step = next(s for s in task.steps if s.step_id == "s1")

    assert maybe_insert_review(_deps(store), task, done_step) is False
    task = store.get("t1")
    assert not [s for s in task.steps if s.step_type == "review"]
    assert task.status != "stalled"
    assert events == ["review_skipped"]


# --- rule 2: review done -> verdict handling ------------------------------------------


def _mint_review(store, task_id="t1", content_step_id="s1", *, reviewer="agent-qa",
                  review_round=0) -> None:
    store.insert_step(task_id, {
        "step_id": f"{content_step_id}-review-{review_round}", "title": "soat",
        "assigned_to": reviewer, "deps": [content_step_id], "step_type": "review",
        "parent_step_id": content_step_id, "review_round": review_round,
    })
    step_id = f"{content_step_id}-review-{review_round}"
    store.mark_done(task_id, step_id, outcome_ref="x", cost_usd=0.0)


def test_passed_verdict_is_a_clean_no_op(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _mint_review(store)
    from my_crew.runtime.team_task_paths import team_tasks_root

    write_review_verdict_artifact(
        team_tasks_root(), "t1", 1, 0, {"passed": True, "failures": []},
    )
    task = store.get("t1")
    review_step = next(s for s in task.steps if s.step_type == "review")

    assert maybe_handle_review_done(_deps(store), task, review_step) is False
    task = store.get("t1")
    assert not [s for s in task.steps if s.step_type == "rework"]
    assert task.status != "stalled"


def test_needs_rework_verdict_mints_rework_step_with_original_author(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _mint_review(store)
    from my_crew.runtime.team_task_paths import team_tasks_root

    write_review_verdict_artifact(
        team_tasks_root(), "t1", 1, 0,
        {"passed": False, "failures": ["thieu so lieu"], "result_text": "brief"},
    )
    task = store.get("t1")
    review_step = next(s for s in task.steps if s.step_type == "review")

    assert maybe_handle_review_done(_deps(store), task, review_step) is True
    task = store.get("t1")
    rework_steps = [s for s in task.steps if s.step_type == "rework"]
    assert len(rework_steps) == 1
    rework = rework_steps[0]
    assert rework.assigned_to == "agent-a"  # original content-step author
    assert rework.parent_step_id == "s1"
    assert rework.review_round == 0
    assert rework.deps == (review_step.step_id,)


def test_rework_round_cap_stalls_and_escalates_after_max_rounds(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _mint_review(store, review_round=MAX_REVIEW_ROUNDS)
    from my_crew.runtime.team_task_paths import team_tasks_root

    write_review_verdict_artifact(
        team_tasks_root(), "t1", 1, MAX_REVIEW_ROUNDS,
        {"passed": False, "failures": ["van sai"], "result_text": "brief"},
    )
    escalated = []
    task = store.get("t1")
    review_step = next(
        s for s in task.steps
        if s.step_type == "review" and s.review_round == MAX_REVIEW_ROUNDS
    )

    deps = _deps(store, escalate=lambda t, s, kind, msg: escalated.append(kind))
    assert maybe_handle_review_done(deps, task, review_step) is True
    task = store.get("t1")
    assert task.status == "stalled"
    assert escalated == ["review_rounds_exhausted"]
    assert not [s for s in task.steps if s.step_type == "rework"]


def test_stale_artifact_remints_a_fresh_review_at_same_round(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _mint_review(store)
    # no verdict artifact written -> stale/missing
    task = store.get("t1")
    review_step = next(s for s in task.steps if s.step_type == "review")

    assert maybe_handle_review_done(_deps(store), task, review_step) is True
    task = store.get("t1")
    review_steps = [s for s in task.steps if s.step_type == "review"]
    assert len(review_steps) == 2  # original + freshly re-minted
    assert all(s.review_round == 0 for s in review_steps)


# --- rule 3: rework done -> next review round -----------------------------------------


def test_rework_done_mints_next_review_round(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _mint_review(store)
    store.insert_step("t1", {
        "step_id": "s1-rework-0", "title": "draft báo cáo", "assigned_to": "agent-a",
        "deps": ["s1-review-0"], "step_type": "rework", "parent_step_id": "s1",
        "review_round": 0,
    })
    store.mark_done("t1", "s1-rework-0", outcome_ref="x", cost_usd=0.0)
    _wire_roster(monkeypatch, [("agent-a", "pm"), ("agent-qa", "pm")])

    task = store.get("t1")
    rework_step = next(s for s in task.steps if s.step_type == "rework")

    assert maybe_insert_review_after_rework(_deps(store), task, rework_step) is True
    task = store.get("t1")
    round1_reviews = [s for s in task.steps if s.step_type == "review" and s.review_round == 1]
    assert len(round1_reviews) == 1
    assert round1_reviews[0].deps == ("s1-rework-0",)


def test_rework_done_next_round_no_reviewer_skips_without_stalling(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store, needs_review=True)
    _mint_review(store)
    store.insert_step("t1", {
        "step_id": "s1-rework-0", "title": "draft báo cáo", "assigned_to": "agent-a",
        "deps": ["s1-review-0"], "step_type": "rework", "parent_step_id": "s1",
        "review_round": 0,
    })
    store.mark_done("t1", "s1-rework-0", outcome_ref="x", cost_usd=0.0)
    _wire_roster(monkeypatch, [("agent-a", "pm")])  # no peer this round

    task = store.get("t1")
    rework_step = next(s for s in task.steps if s.step_type == "rework")

    assert maybe_insert_review_after_rework(_deps(store), task, rework_step) is False
    task = store.get("t1")
    assert not [s for s in task.steps if s.step_type == "review" and s.review_round == 1]
    assert task.status != "stalled"
