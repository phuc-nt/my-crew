"""M32 rework round cap end-to-end via `run_one_tick`: three consecutive "needs_rework"
verdicts against the SAME content step mint exactly 2 rework rounds (round 0, round 1)
then stall on the would-be 3rd — never a round-2 rework row. `review_round` persists
across a fresh store handle (reload), proving it survives a reboot/amend the same way
every other persisted column does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from my_crew.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker, run_one_tick
from my_crew.agent.coordinator_nodes.review_insert import MAX_REVIEW_ROUNDS
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


def _plan_one_step(store: TeamTaskStore, task_id="t1") -> None:
    steps = [
        {"step_id": "s1", "title": "draft báo cáo", "assigned_to": "agent-a", "deps": [],
         "needs_review": True},
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
    import my_crew.agent.team_task_roster as roster_mod

    monkeypatch.setattr(roster_mod, "assignable_staff", lambda: list(roster))


def _fail_newest_review(store, tmp_path) -> None:
    """Complete the newest pending/running review-step and write a "needs_rework"
    verdict for it — simulates the review-step's worker having already run."""
    from my_crew.runtime.team_task_paths import team_tasks_root

    task = store.get("t1")
    review = max(
        (s for s in task.steps if s.step_type == "review" and s.status != "done"),
        key=lambda s: s.seq,
    )
    store.mark_done("t1", review.step_id, outcome_ref="x", cost_usd=0.0)
    write_review_verdict_artifact(
        team_tasks_root(), "t1", 1, review.review_round,
        {"passed": False, "failures": [f"vòng {review.review_round}: vẫn thiếu số liệu"],
         "result_text": "báo cáo vẫn sơ sài"},
    )


def _complete_newest_rework(store) -> None:
    task = store.get("t1")
    rework = max(
        (s for s in task.steps if s.step_type == "rework" and s.status != "done"),
        key=lambda s: s.seq,
    )
    store.mark_done("t1", rework.step_id, outcome_ref="x", cost_usd=0.0)


def test_three_consecutive_failures_cap_at_two_rework_rounds_then_stall(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store)
    _wire_roster(monkeypatch, [("agent-a", "pm"), ("agent-qa", "pm")])
    deps = _deps(store)

    # Tick 1: mints round-0 review-step.
    result = run_one_tick(deps)
    assert result.action == "review_inserted"

    # Round-0 review fails -> tick mints rework-0.
    _fail_newest_review(store, tmp_path)
    result = run_one_tick(deps)
    assert result.action == "rework_inserted"

    # rework-0 completes -> tick mints round-1 review.
    _complete_newest_rework(store)
    result = run_one_tick(deps)
    assert result.action == "review_inserted"

    # Round-1 review fails -> tick mints rework-1 (2nd and LAST allowed round).
    _fail_newest_review(store, tmp_path)
    result = run_one_tick(deps)
    assert result.action == "rework_inserted"

    task = store.get("t1")
    rework_rounds = sorted(s.review_round for s in task.steps if s.step_type == "rework")
    assert rework_rounds == [0, 1]

    # rework-1 completes -> tick mints round-2 review (still within cap: MAX_REVIEW_ROUNDS=2).
    _complete_newest_rework(store)
    result = run_one_tick(deps)
    assert result.action == "review_inserted"

    task = store.get("t1")
    review_rounds = sorted({s.review_round for s in task.steps if s.step_type == "review"})
    assert review_rounds == [0, 1, 2]

    # Round-2 review ALSO fails -> this is round == MAX_REVIEW_ROUNDS -> EXPLICIT stall,
    # never a 3rd rework round.
    _fail_newest_review(store, tmp_path)
    result = run_one_tick(deps)
    assert result.action == "stalled"

    task = store.get("t1")
    assert task.status == "stalled"
    rework_rounds_final = sorted(s.review_round for s in task.steps if s.step_type == "rework")
    assert rework_rounds_final == [0, 1]  # never a round-2 rework
    assert MAX_REVIEW_ROUNDS == 2


def test_review_round_persists_across_store_reload(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _plan_one_step(store)
    _wire_roster(monkeypatch, [("agent-a", "pm"), ("agent-qa", "pm")])
    deps = _deps(store)

    run_one_tick(deps)  # mints round-0 review
    _fail_newest_review(store, tmp_path)
    run_one_tick(deps)  # mints rework-0
    _complete_newest_rework(store)
    run_one_tick(deps)  # mints round-1 review

    # Fresh store handle over the SAME sqlite file — simulates a reboot/reload; the
    # persisted review_round column must read back identically, not reset to 0.
    reloaded = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    task = reloaded.get("t1")
    review_rounds = sorted({s.review_round for s in task.steps if s.step_type == "review"})
    assert review_rounds == [0, 1]
    rework_rounds = sorted(s.review_round for s in task.steps if s.step_type == "rework")
    assert rework_rounds == [0]
