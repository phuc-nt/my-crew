"""Peer review must be able to trace the figures it grades back to their source.

`team_step_runner._run_review` is the only place that can supply this: the reviewer's
own `deps` point at the row being GRADED (the answer), so the reviewed step's INPUT has
to be read separately, from the CONTENT step's deps. Until it was, peer review graded
output-only — and a result fabricated from a "KHÔNG CÓ KẾT QUẢ" input passed 3/3 on the
fleet model, because with only the answer and the rubric in view a well-formed invention
satisfies exactly the criteria it was invented to satisfy.

The narrow prompt-shape assertions live in `test_review_graph.py`; this file proves the
real dispatch actually populates the field from a real two-step DAG + real artifacts.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from my_crew.agent.task_decomposition import decomposition_content_hash
from my_crew.agent.team_task_artifact import write_step_artifact
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


def _content_hash(steps: list[dict]) -> str:
    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(
            step_id=s["step_id"], title=s["title"], assigned_to=s["assigned_to"],
            deps=tuple(s.get("deps", ())),
        )
        for s in steps
    ]))


def _two_step_task_with_review(tmp_path, *, research_output: str):
    """s1 (research) -> s2 (write-up, deps=[s1]) -> review of s2.

    `research_output` is what s1 produced and therefore exactly what s2 was handed —
    the block the reviewer must see.
    """
    from my_crew.runtime.team_task_paths import team_tasks_root

    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    steps = [
        {"step_id": "s1", "title": "tìm giá thuê", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s2", "title": "viết bảng giá", "assigned_to": "agent-b", "deps": ["s1"],
         "needs_review": True},
    ]
    store.create_task(task_id="t1", title="demo", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))

    a1 = store.reserve_step("t1", "s1")
    write_step_artifact(team_tasks_root(), "t1", 1, {"result_text": research_output, "version": a1})
    store.mark_done("t1", "s1", outcome_ref="x", cost_usd=0.0, attempt_id=a1)

    a2 = store.reserve_step("t1", "s2")
    write_step_artifact(
        team_tasks_root(), "t1", 2,
        {"result_text": "| Bitexco | 62 USD | CBRE Q2/2026 |", "version": a2},
    )
    store.mark_done("t1", "s2", outcome_ref="x", cost_usd=0.0, attempt_id=a2)
    return store, a2


def _wire_llm(monkeypatch):
    calls: list[list[dict]] = []

    class _FakeLlm:
        def __init__(self, _settings):
            pass

        def complete(self, messages, **_kw):
            calls.append(messages)
            return SimpleNamespace(
                content=json.dumps({"passed": True, "failures": [], "notes": []}), cost_usd=0.01,
            )

    import my_crew.llm.client as llm_client_mod

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)
    return calls


def _run_review_dispatch(store, tmp_path):
    from my_crew.config.config_builders import build_settings_from_dict
    from my_crew.runtime.team_step_runner import _run_review

    task = store.get("t1")
    review_step = SimpleNamespace(
        step_id="r1", parent_step_id="s2", deps=("s2",), review_round=0, step_type="review",
    )
    assert any(s.step_id == "s2" for s in task.steps)
    return _run_review(
        None, build_settings_from_dict({"data_dir": tmp_path}),
        task_id="t1", step=review_step, store=store,
    )


def test_reviewer_receives_the_upstream_result_the_reviewed_step_worked_from(
    tmp_path, monkeypatch,
):
    store, _ = _two_step_task_with_review(
        tmp_path, research_output="KHÔNG CÓ KẾT QUẢ TÌM KIẾM — công cụ web trả về rỗng.",
    )
    calls = _wire_llm(monkeypatch)
    try:
        _run_review_dispatch(store, tmp_path)
    finally:
        store.close()

    user = calls[0][1]["content"]
    # The reviewer can now see that the step it is grading was handed nothing — which is
    # what makes the cited CBRE figure recognisably invented rather than merely unfamiliar.
    assert "KHÔNG CÓ KẾT QUẢ TÌM KIẾM" in user
    assert "ĐẦU VÀO bước này nhận được" in user


def test_handoff_comes_from_the_reviewed_steps_deps_not_the_review_steps_own_deps(
    tmp_path, monkeypatch,
):
    """The review step's `deps` point at the GRADED row (s2 — the answer). If the wiring
    read those instead of the content step's deps, the "input" block would just be the
    answer echoed back, and the reviewer would still be blind.
    """
    store, _ = _two_step_task_with_review(tmp_path, research_output="giá thuê trung bình 55 USD")
    calls = _wire_llm(monkeypatch)
    try:
        _run_review_dispatch(store, tmp_path)
    finally:
        store.close()

    user = calls[0][1]["content"]
    head, _, tail = user.partition("ĐẦU VÀO bước này nhận được")
    assert tail, "handoff block missing"
    input_block = tail.split("kết quả cần soát")[0]
    assert "giá thuê trung bình 55 USD" in input_block  # s1's output = what s2 was given
    assert "Bitexco" not in input_block  # NOT s2's own output fed back as its input


def test_first_step_with_no_deps_grades_output_only(tmp_path, monkeypatch):
    """No deps ⇒ nothing was handed over ⇒ no input block at all. Showing an EMPTY one
    would read to the model as "the input was empty", i.e. the exact fabrication signal,
    and would fail honest first steps."""
    from my_crew.runtime.team_task_paths import team_tasks_root

    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    steps = [{"step_id": "s1", "title": "viết mở đầu", "assigned_to": "agent-a", "deps": [],
              "needs_review": True}]
    store.create_task(task_id="t1", title="demo", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    a1 = store.reserve_step("t1", "s1")
    write_step_artifact(team_tasks_root(), "t1", 1, {"result_text": "mở đầu", "version": a1})
    store.mark_done("t1", "s1", outcome_ref="x", cost_usd=0.0, attempt_id=a1)

    calls = _wire_llm(monkeypatch)
    from my_crew.config.config_builders import build_settings_from_dict
    from my_crew.runtime.team_step_runner import _run_review

    review_step = SimpleNamespace(
        step_id="r1", parent_step_id="s1", deps=("s1",), review_round=0, step_type="review",
    )
    try:
        _run_review(
            None, build_settings_from_dict({"data_dir": tmp_path}),
            task_id="t1", step=review_step, store=store,
        )
    finally:
        store.close()

    assert "ĐẦU VÀO bước này nhận được" not in calls[0][1]["content"]
