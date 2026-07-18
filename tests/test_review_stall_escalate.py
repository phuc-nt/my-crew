"""M32 explicit stall+escalate at `review_round == MAX_REVIEW_ROUNDS` (`review_insert
.maybe_handle_review_done`): every step involved is `done` (never `failed`/`timeout`),
so v12's `_dead_end_result` path can never see this case — the stall must come from
this module's OWN explicit `set_task_status(stalled)` + `escalate(...,
"review_rounds_exhausted", ...)` call, not from the dead-end fallback.
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


def _plan_with_final_round_review(store, tmp_path) -> None:
    """A task whose content step, at `review_round == MAX_REVIEW_ROUNDS`, has a `done`
    review-step with a "needs_rework" verdict already on disk — every row involved is
    `done`, matching the phase's "no failed/timeout anywhere" requirement."""
    steps = [
        {"step_id": "s1", "title": "draft báo cáo", "assigned_to": "agent-a", "deps": [],
         "needs_review": True},
    ]
    store.create_task(task_id="t1", title="demo task", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    store.mark_done("t1", "s1", outcome_ref="x", cost_usd=0.0)
    store.insert_step("t1", {
        "step_id": f"s1-review-{MAX_REVIEW_ROUNDS}", "title": "soat",
        "assigned_to": "agent-qa", "deps": ["s1"], "step_type": "review",
        "parent_step_id": "s1", "review_round": MAX_REVIEW_ROUNDS,
    })
    store.mark_done(
        "t1", f"s1-review-{MAX_REVIEW_ROUNDS}", outcome_ref="x", cost_usd=0.0,
    )
    from my_crew.runtime.team_task_paths import team_tasks_root

    write_review_verdict_artifact(
        team_tasks_root(), "t1", 1, MAX_REVIEW_ROUNDS,
        {"passed": False, "failures": ["vẫn sai"], "result_text": "brief"},
    )


def test_max_round_needs_rework_is_explicit_stall_not_dead_end(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_with_final_round_review(store, tmp_path)
    escalated: list[tuple[str, str]] = []
    deps = _deps(store, escalate=lambda task, step, kind, msg: escalated.append((kind, msg)))

    task = store.get("t1")
    assert all(s.status == "done" for s in task.steps)  # no failed/timeout anywhere
    review_step = next(
        s for s in task.steps
        if s.step_type == "review" and s.review_round == MAX_REVIEW_ROUNDS
    )

    handled = maybe_handle_review_done(deps, task, review_step)

    assert handled is True
    task = store.get("t1")
    assert task.status == "stalled"
    assert len(escalated) == 1
    kind, message = escalated[0]
    assert kind == "review_rounds_exhausted"
    assert "soát chéo" in message or "soat" in message.lower()
    # No round-3 rework was ever minted — the cap holds.
    assert not [s for s in task.steps if s.step_type == "rework"]


def test_max_round_stall_never_relies_on_dead_end_path(tmp_path, monkeypatch):
    """`_dead_end_result` only fires on `failed`/`timeout` steps — with every step
    `done`, the ticker's dead-end branch would find nothing; the stall MUST come from
    `maybe_handle_review_done`'s own explicit call, proven here by calling
    `_dead_end_result` directly against the same task state and asserting it is a
    no-op (returns None, does not itself stall anything)."""
    from my_crew.agent.coordinator_graph import _dead_end_result

    store = _store(tmp_path)
    _plan_with_final_round_review(store, tmp_path)
    deps = _deps(store)
    task = store.get("t1")

    assert _dead_end_result(deps, task) is None
    task = store.get("t1")
    assert task.status != "stalled"  # dead-end path alone never stalls this task
