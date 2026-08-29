"""Review cap (`review_round == MAX_REVIEW_ROUNDS` / task budget) ENDS the chain with
zero side effects (`review_insert.maybe_handle_review_done`): no stall, no escalate,
no reflection, no further mint. The pre-lanes10 behaviour — explicit stall + escalate
— let a reviewer flip-flopping over ambiguous ground truth hold a fully-done task
hostage (lanes9b: 3/4 cases stalled at review-2-2 with every content step done).
The objection now reaches the CEO through the delivery aggregate's deterministic
"Soát chéo chưa đạt" header (`team_tick_collaborators`, tested there), not through a
stall. Zero side effects is a hard requirement, not a nicety: done rows are
re-inspected EVERY tick, so anything this branch did would repeat forever.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from my_crew.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker
from my_crew.agent.coordinator_nodes.review_insert import (
    MAX_REVIEW_ROUNDS,
    maybe_handle_review_done,
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
    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(
            step_id=s["step_id"], title=s["title"], assigned_to=s["assigned_to"],
            deps=tuple(s.get("deps", ())),
        )
        for s in steps
    ]))


def _deps(store, **overrides) -> CoordinatorDeps:
    base = dict(
        store=store, retry_tracker=in_memory_retry_tracker(), cost_cap_usd=2.0,
        escalate=lambda task, step, kind, msg: None, now=lambda: datetime.now(UTC),
    )
    base.update(overrides)
    return CoordinatorDeps(**base)


def _plan_with_final_round_review(store) -> None:
    """A task whose content step, at `review_round == MAX_REVIEW_ROUNDS`, has a `done`
    review-step with a "needs_rework" verdict already on disk — every row involved is
    `done` (never `failed`/`timeout`), so v12's `_dead_end_result` can never see it."""
    steps = [
        {"step_id": "s1", "title": "draft báo cáo", "assigned_to": "agent-a", "deps": [],
         "needs_review": True},
    ]
    store.create_task(task_id="t1", title="demo task", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    store.reserve_step("t1", "s1")
    store.mark_done("t1", "s1", outcome_ref="x", cost_usd=0.0)
    store.insert_step("t1", {
        "step_id": f"s1-review-{MAX_REVIEW_ROUNDS}", "title": "soat",
        "assigned_to": "agent-qa", "deps": ["s1"], "step_type": "review",
        "parent_step_id": "s1", "review_round": MAX_REVIEW_ROUNDS,
    })
    store.reserve_step("t1", f"s1-review-{MAX_REVIEW_ROUNDS}")
    store.mark_done(
        "t1", f"s1-review-{MAX_REVIEW_ROUNDS}", outcome_ref="x", cost_usd=0.0,
    )
    from my_crew.runtime.team_task_paths import team_tasks_root

    write_review_verdict_artifact(
        team_tasks_root(), "t1", 1, MAX_REVIEW_ROUNDS,
        {"passed": False, "failures": ["vẫn sai"], "result_text": "brief"},
    )


def _final_review(task):
    return next(
        s for s in task.steps
        if s.step_type == "review" and s.review_round == MAX_REVIEW_ROUNDS
    )


def test_max_round_needs_rework_ends_the_chain_with_zero_side_effects(tmp_path):
    store = _store(tmp_path)
    _plan_with_final_round_review(store)
    escalated: list[tuple[str, str]] = []
    reflected: list[tuple[str, str, str]] = []
    deps = _deps(
        store,
        escalate=lambda task, step, kind, msg: escalated.append((kind, msg)),
        reflect=lambda task, outcome, detail: reflected.append((task.id, outcome, detail)),
    )

    task = store.get("t1")
    assert all(s.status == "done" for s in task.steps)  # no failed/timeout anywhere

    handled = maybe_handle_review_done(deps, task, _final_review(task))

    assert handled is False
    task = store.get("t1")
    assert task.status != "stalled"
    assert escalated == []
    assert reflected == []
    # No round-3 rework and no fresh review was ever minted — the cap holds.
    assert not [s for s in task.steps if s.step_type == "rework"]
    assert len([s for s in task.steps if s.step_type == "review"]) == 1


def test_cap_branch_is_idempotent_across_repeated_ticks(tmp_path):
    """Done rows are re-inspected every tick; the cap branch must be a no-op on every
    one of them, not just the first — a repeated escalate/status write here is spam."""
    store = _store(tmp_path)
    _plan_with_final_round_review(store)
    escalated: list[str] = []
    deps = _deps(store, escalate=lambda task, step, kind, msg: escalated.append(kind))

    for _ in range(3):
        task = store.get("t1")
        assert maybe_handle_review_done(deps, task, _final_review(task)) is False

    task = store.get("t1")
    assert task.status != "stalled"
    assert escalated == []
    assert len(task.steps) == 2  # content + the one done review, untouched


def test_dead_end_path_also_sees_nothing_so_the_task_never_stalls(tmp_path):
    """`_dead_end_result` only fires on `failed`/`timeout` steps — with every step
    `done` AND the cap branch minting nothing, NO path stalls this task: it proceeds
    to the normal aggregate/delivery, which carries the reviewer's objection."""
    from my_crew.agent.coordinator_graph import _dead_end_result

    store = _store(tmp_path)
    _plan_with_final_round_review(store)
    deps = _deps(store)
    task = store.get("t1")

    assert maybe_handle_review_done(deps, task, _final_review(task)) is False
    assert _dead_end_result(deps, store.get("t1")) is None
    assert store.get("t1").status != "stalled"
