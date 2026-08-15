"""v34 P5: acceptance-criteria review — per-criterion verdicts ride the existing
criteria-anchored machinery end to end.

Load-bearing:
- CheckVerdict/ReviewVerdict parse the optional `criteria` checklist; pre-P5 model
  output (no field) still parses — backward compatible.
- run_review_step writes the checklist into the verdict artifact and returns it.
- the review room event carries COUNTS only (never criterion text) and the
  projection allowlist passes them through.
- decompose prompt demands measurable, CEO-honoring criteria (prompt contract).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from my_crew.agent.review_graph import (
    ReviewStepInput,
    ReviewVerdictError,
    parse_review_verdict,
    run_review_step,
)
from my_crew.llm.team_task_check_prompt import parse_check_verdict


def test_check_verdict_parses_optional_criteria_checklist():
    v = parse_check_verdict(json.dumps({
        "passed": False, "failures": ["thiếu nguồn"], "confidence": 0.8,
        "criteria": [
            {"criterion": "có 3 nguồn trích dẫn", "passed": False, "note": "chỉ 1 nguồn"},
            {"criterion": "dưới 500 từ", "passed": True, "note": "420 từ"},
        ],
    }))
    assert len(v.criteria) == 2 and v.criteria[0].passed is False
    # pre-P5 shape (no criteria field) still parses
    old = parse_check_verdict('{"passed": true, "failures": [], "confidence": 1.0}')
    assert old.criteria == []


def test_review_verdict_parses_criteria_and_stays_backward_compatible():
    v = parse_review_verdict(json.dumps({
        "passed": True, "failures": [],
        "criteria": [{"criterion": "đúng format", "passed": True, "note": "ok"}],
    }))
    assert v.criteria and v.criteria[0]["criterion"] == "đúng format"
    assert parse_review_verdict('{"passed": false, "failures": ["x"]}').criteria == []


def test_run_review_step_threads_criteria_into_artifact_and_result(tmp_path, monkeypatch):
    from my_crew.agent.team_task_artifact import write_step_artifact

    write_step_artifact(tmp_path, "t1", 3, {
        "status": "done", "result_text": "bản nháp", "step_title": "Soạn",
        "attempt": "v1", "version": "v1", "self_check_failed": False,
    })

    class _FakeLlm:
        def __init__(self, settings):
            pass

        def complete(self, messages, **_kw):
            return SimpleNamespace(content=json.dumps({
                "passed": False, "failures": ["thiếu số liệu"],
                "criteria": [
                    {"criterion": "có số liệu", "passed": False, "note": "không thấy"},
                    {"criterion": "văn phong", "passed": True, "note": "ổn"},
                ],
            }), cost_usd=0.01, prompt_tokens=10, completion_tokens=5)

    import my_crew.llm.client as llm_client_mod

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)

    out = run_review_step(
        None, SimpleNamespace(), data_dir=tmp_path,
        review_input=ReviewStepInput(
            task_id="t1", graded_seq=3, verdict_seq=4, review_round=0,
            locked_version="v1", acceptance="- có số liệu\n- văn phong",
            step_title="Soạn",
        ),
    )
    assert out["passed"] is False and len(out["criteria"]) == 2

    from my_crew.agent.team_task_artifact import review_verdict_artifact_path

    payload = json.loads(
        review_verdict_artifact_path(tmp_path, "t1", 4, 0).read_text(encoding="utf-8"))
    assert payload["criteria"][0]["criterion"] == "có số liệu"


@pytest.mark.parametrize("passed", [True, False])
def test_failures_appendix_rides_result_text_only_on_failed_verdicts(
    tmp_path, monkeypatch, passed
):
    """A passed review must hand the prior output on UNTOUCHED — the
    "Danh sách lỗi cần sửa" appendix (with its "(không có chi tiết)" placeholder)
    is a rework brief, meaningless on user-facing surfaces when nothing failed."""
    from my_crew.agent.team_task_artifact import (
        review_verdict_artifact_path,
        write_step_artifact,
    )

    write_step_artifact(tmp_path, "t1", 3, {
        "status": "done", "result_text": "bản nháp", "step_title": "Soạn",
        "attempt": "v1", "version": "v1", "self_check_failed": False,
    })

    class _FakeLlm:
        def __init__(self, settings):
            pass

        def complete(self, messages, **_kw):
            return SimpleNamespace(
                content=json.dumps({
                    "passed": passed,
                    "failures": [] if passed else ["thiếu số liệu"],
                }),
                cost_usd=0.01, prompt_tokens=10, completion_tokens=5,
            )

    import my_crew.llm.client as llm_client_mod

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)

    run_review_step(
        None, SimpleNamespace(), data_dir=tmp_path,
        review_input=ReviewStepInput(
            task_id="t1", graded_seq=3, verdict_seq=4, review_round=0,
            locked_version="v1", acceptance="- có số liệu", step_title="Soạn",
        ),
    )

    payload = json.loads(
        review_verdict_artifact_path(tmp_path, "t1", 4, 0).read_text(encoding="utf-8"))
    if passed:
        assert payload["result_text"] == "bản nháp"
        assert "Danh sách lỗi" not in payload["result_text"]
    else:
        assert payload["result_text"].startswith("bản nháp")
        assert "Danh sách lỗi cần sửa:\n- thiếu số liệu" in payload["result_text"]


def test_review_event_carries_counts_only(monkeypatch):
    from my_crew.runtime import team_step_runner as runner

    captured = {}
    monkeypatch.setattr(
        "my_crew.runtime.office_room_append.append_office_event",
        lambda room, *, author, kind, body, also_office=False: captured.update(body),
    )
    monkeypatch.setattr("my_crew.runtime.office_room_append.room_for_task", lambda t: t)
    runner._append_review_event(
        "t1", author="qa", task_title="T", step_title="S", passed=False,
        failures=["a", "b"],
        criteria=[{"criterion": "c1", "passed": True}, {"criterion": "c2", "passed": False}],
    )
    assert captured["criteria_total"] == 2 and captured["criteria_passed"] == 1
    assert "criteria" not in captured  # texts never reach the room
    assert "attempt_id" not in captured  # không truyền ⇒ không field rỗng (event cũ)


def test_review_event_carries_opaque_attempt_id(monkeypatch):
    """v58 P4: attempt_id MỜ đi kèm event review (identifier, không phải content) —
    FE tray join thẳng capture, retry cùng round hết lẫn."""
    from my_crew.runtime import team_step_runner as runner

    captured = {}
    monkeypatch.setattr(
        "my_crew.runtime.office_room_append.append_office_event",
        lambda room, *, author, kind, body, also_office=False: captured.update(body),
    )
    monkeypatch.setattr("my_crew.runtime.office_room_append.room_for_task", lambda t: t)
    runner._append_review_event(
        "t1", author="qa", task_title="T", step_title="S", passed=True,
        failures=[], criteria=[{"criterion": "c1", "passed": True}], attempt_id="att-9",
    )
    assert captured["attempt_id"] == "att-9"
    assert "criteria" not in captured  # posture không đổi


def test_projection_passes_criteria_counts():
    from my_crew.server.office_event_projection import summarize_office_event

    body = summarize_office_event("review", {
        "task_title": "T", "step_title": "S", "verdict": "needs_rework",
        "failure_count": 2, "criteria_total": 3, "criteria_passed": 1,
        "assigned_to": "qa", "attempt_id": "att-9",
        "criteria": [{"criterion": "bí mật nội dung"}],  # must NOT pass through
    })
    assert body["criteria_total"] == 3 and body["criteria_passed"] == 1
    assert body["attempt_id"] == "att-9"  # v58 P4: id mờ qua allowlist
    assert "criteria" not in body


def test_decompose_prompt_demands_measurable_criteria():
    from my_crew.llm.team_task_prompt import _DECOMPOSE_SYSTEM

    assert "ĐO ĐƯỢC" in _DECOMPOSE_SYSTEM
    assert "CEO nêu tiêu chí" in _DECOMPOSE_SYSTEM


def test_decompose_prompt_demands_a_data_freshness_criterion_for_web_steps():
    """Live UAT: a reviewer passed 7/2024 pricing for a 2026 question because no
    criterion asked about recency. The rule stays snippet-compatible — it demands a
    NOTE when the source itself dates its data, never source metadata (access dates)
    the excerpt cannot carry, and never rejects old figures with no newer source."""
    from my_crew.llm.team_task_prompt import _DECOMPOSE_SYSTEM

    assert "ĐỘ TƯƠI" in _DECOMPOSE_SYSTEM
    assert "KHÔNG loại số liệu chỉ vì cũ" in _DECOMPOSE_SYSTEM


def test_parsers_tolerate_markdown_fences_and_leading_prose():
    """v34 UAT finding: a reviewer model wrapped its verdict in ```json fences →
    parse died → review step failed → whole task stalled. Every LLM-JSON parser now
    strips fences/prose deterministically; genuine garbage still fails loud."""
    from my_crew.agent.review_graph import parse_review_verdict
    from my_crew.agent.task_decomposition import DecompositionError, parse_decomposed_task
    from my_crew.llm.team_task_check_prompt import parse_check_verdict

    fenced = '```json\n{"passed": true, "failures": []}\n```'
    assert parse_review_verdict(fenced).passed is True
    prose = 'Đây là kết quả thẩm định:\n{"passed": false, "failures": ["x"], "confidence": 0.9}'
    assert parse_check_verdict(prose).passed is False
    with pytest.raises(ReviewVerdictError):
        parse_review_verdict("hoàn toàn không có JSON")
    import pytest as _pt
    with _pt.raises(DecompositionError):
        parse_decomposed_task("không JSON")
