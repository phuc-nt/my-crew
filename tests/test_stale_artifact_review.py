"""End-to-end stale-artifact re-review: a content step re-runs to a NEW attempt AFTER
its review-step was already minted and locked to the OLD attempt's artifact — the
reviewer's own worker run (`review_graph.run_review_step`, dispatched through
`team_step_runner._run_review`) must refuse to grade the stale content (never call the
LLM against it, never write a verdict), and the ticker rule
(`review_insert.maybe_handle_review_done`, driven here through the real `run_one_tick`)
must re-mint a FRESH review-step at the same round instead of ever stalling the task on
a review that graded content nobody will see delivered.

The individual halves of this (stale-artifact detection inside `run_review_step`;
ticker re-mint given a `None` verdict) are already covered narrowly in
`test_review_graph.py`/`test_review_insert_rule.py`; this test proves the FULL path
end to end, including a genuine content-step re-run (a fresh `attempt_id` via
`reserve_step`, not a hand-constructed mismatch).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from my_crew.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker, run_one_tick
from my_crew.agent.task_decomposition import decomposition_content_hash
from my_crew.agent.team_task_artifact import write_step_artifact
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
        store=store,
        retry_tracker=in_memory_retry_tracker(),
        cost_cap_usd=2.0,
        spawn_step=lambda task, step, attempt_id: 999,
        pid_alive=lambda pid: True,
        kill_pid=lambda pid, attempt_id: None,
        roster_ok=lambda agent_id: True,
        aggregate=lambda task: ("done summary", 0.01),
        deliver_room=lambda task, summary: None,
        escalate=lambda task, step, kind, msg: None,
        now=lambda: datetime.now(UTC),
    )
    base.update(overrides)
    return CoordinatorDeps(**base)


def test_content_rerun_after_review_minted_forces_stale_artifact_reject_and_remint(
    tmp_path, monkeypatch,
):
    from my_crew.runtime.team_task_paths import team_tasks_root

    store = _store(tmp_path)
    steps = [
        {"step_id": "s1", "title": "draft báo cáo", "assigned_to": "agent-a", "deps": [],
         "needs_review": True},
    ]
    store.create_task(task_id="t1", title="demo", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))

    # Content step's FIRST attempt finishes done -> writes its own artifact under the
    # attempt_id it was reserved with.
    first_attempt = store.reserve_step("t1", "s1")
    write_step_artifact(
        team_tasks_root(), "t1", 1, {"result_text": "bản nháp đầu", "version": first_attempt},
    )
    store.mark_done("t1", "s1", outcome_ref="x", cost_usd=0.0, attempt_id=first_attempt)

    # Ticker rule mints the review-step, locked to the FIRST attempt's artifact.
    import my_crew.agent.team_task_roster as roster_mod

    monkeypatch.setattr(roster_mod, "assignable_staff",
                        lambda: [("agent-a", "pm"), ("agent-qa", "pm")])
    result = run_one_tick(_deps(store))
    assert result.action == "review_inserted"
    task = store.get("t1")
    review_steps = [s for s in task.steps if s.step_type == "review"]
    assert len(review_steps) == 1
    review_step = review_steps[0]
    assert review_step.review_round == 0

    # Content step RE-RUNS (e.g. a retry) to a NEW attempt, overwriting its own artifact
    # with a version the already-minted review-step was never locked to.
    second_attempt = store.reserve_step("t1", "s1")
    assert second_attempt != first_attempt
    write_step_artifact(
        team_tasks_root(), "t1", 1, {"result_text": "bản nháp lần hai", "version": second_attempt},
    )
    store.mark_done("t1", "s1", outcome_ref="x", cost_usd=0.0, attempt_id=second_attempt)

    # The reviewer's own worker run (real `run_review_step`, through the SAME dispatch
    # `team_step_runner._run_review` uses) refuses to grade stale content: never calls
    # the LLM, never writes a verdict artifact.
    import my_crew.llm.client as llm_client_mod
    from my_crew.agent.review_graph import ReviewStepInput, run_review_step
    from my_crew.agent.team_task_artifact import read_review_verdict_artifact
    from my_crew.config.config_builders import build_settings_from_dict

    llm_calls: list[list[dict]] = []

    class _FakeLlm:
        def __init__(self, _settings):
            pass

        def complete(self, messages):
            llm_calls.append(messages)
            return SimpleNamespace(
                content=json.dumps({"passed": True, "failures": []}), cost_usd=0.02,
            )

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)
    settings = build_settings_from_dict({"data_dir": tmp_path})

    review_input = ReviewStepInput(
        task_id="t1", graded_seq=1, verdict_seq=1, review_round=0,
        # locked to the FIRST attempt — the review-step was minted before the re-run.
        locked_version=first_attempt,
        acceptance="", step_title="draft báo cáo",
    )
    worker_result = run_review_step(
        None, settings, data_dir=team_tasks_root(), review_input=review_input,
    )
    assert worker_result["status"] == "stale_artifact"
    assert worker_result["delivered"] is False
    assert llm_calls == []  # never grades content that will never be delivered
    assert read_review_verdict_artifact(team_tasks_root(), "t1", 1, 0) is None

    # No verdict was ever written -> mark the review-step done anyway (the worker's own
    # completion, independent of grading outcome — mirrors `_run_review`'s dispatch: a
    # `stale_artifact` result still lets the step reach `done` so the ticker's
    # `maybe_handle_review_done` "verdict is None" branch can react to it).
    review_task = store.get("t1")
    live_review_step = next(s for s in review_task.steps if s.step_type == "review")
    store.mark_done("t1", live_review_step.step_id, attempt_id=live_review_step.attempt_id)

    # Ticker's next tick: review-step is `done` with no verdict artifact -> re-mints a
    # FRESH review-step at the SAME round, never stalls, never double-mints beyond one.
    # `coordinator_graph._maybe_insert_review_rows` labels EVERY mint reached through a
    # `done` `review`-type step as `"rework_inserted"` regardless of whether the actual
    # row minted was a rework or (as here) a fresh re-review — the label only
    # distinguishes "acted on a done review step" from "acted on a done work step"; the
    # real proof of WHAT was minted is the steps list itself, asserted below.
    remint_result = run_one_tick(_deps(store))
    assert remint_result.action == "rework_inserted"
    task_after = store.get("t1")
    review_steps_after = [s for s in task_after.steps if s.step_type == "review"]
    assert len(review_steps_after) == 2  # original (now done, stale) + freshly re-minted
    assert all(s.review_round == 0 for s in review_steps_after)
    assert task_after.status not in ("stalled",)

    # Idempotent: a further tick against the SAME (already re-minted, still `pending`)
    # state does not mint a third review row — it dispatches the fresh review instead.
    third_tick = run_one_tick(_deps(store))
    assert third_tick.action in ("spawned", "none")
    task_final = store.get("t1")
    assert len([s for s in task_final.steps if s.step_type == "review"]) == 2
