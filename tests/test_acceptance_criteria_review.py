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

from src.agent.review_graph import ReviewStepInput, parse_review_verdict, run_review_step
from src.llm.team_task_check_prompt import parse_check_verdict


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
    from src.agent import review_graph
    from src.agent.team_task_artifact import write_step_artifact

    write_step_artifact(tmp_path, "t1", 3, {
        "status": "done", "result_text": "bản nháp", "step_title": "Soạn",
        "attempt": "v1", "version": "v1", "self_check_failed": False,
    })

    class _FakeLlm:
        def __init__(self, settings):
            pass

        def complete(self, messages):
            return SimpleNamespace(content=json.dumps({
                "passed": False, "failures": ["thiếu số liệu"],
                "criteria": [
                    {"criterion": "có số liệu", "passed": False, "note": "không thấy"},
                    {"criterion": "văn phong", "passed": True, "note": "ổn"},
                ],
            }), cost_usd=0.01, prompt_tokens=10, completion_tokens=5)

    import src.llm.client as llm_client_mod

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

    from src.agent.team_task_artifact import review_verdict_artifact_path

    payload = json.loads(
        review_verdict_artifact_path(tmp_path, "t1", 4, 0).read_text(encoding="utf-8"))
    assert payload["criteria"][0]["criterion"] == "có số liệu"


def test_review_event_carries_counts_only(monkeypatch):
    from src.runtime import team_step_runner as runner

    captured = {}
    monkeypatch.setattr(
        "src.runtime.office_room_append.append_office_event",
        lambda room, *, author, kind, body, also_office=False: captured.update(body),
    )
    monkeypatch.setattr("src.runtime.office_room_append.room_for_task", lambda t: t)
    runner._append_review_event(
        "t1", author="kiem-dinh", task_title="T", step_title="S", passed=False,
        failures=["a", "b"],
        criteria=[{"criterion": "c1", "passed": True}, {"criterion": "c2", "passed": False}],
    )
    assert captured["criteria_total"] == 2 and captured["criteria_passed"] == 1
    assert "criteria" not in captured  # texts never reach the room


def test_projection_passes_criteria_counts():
    from src.server.office_event_projection import summarize_office_event

    body = summarize_office_event("review", {
        "task_title": "T", "step_title": "S", "verdict": "needs_rework",
        "failure_count": 2, "criteria_total": 3, "criteria_passed": 1,
        "assigned_to": "kiem-dinh",
        "criteria": [{"criterion": "bí mật nội dung"}],  # must NOT pass through
    })
    assert body["criteria_total"] == 3 and body["criteria_passed"] == 1
    assert "criteria" not in body


def test_decompose_prompt_demands_measurable_criteria():
    from src.llm.team_task_prompt import _DECOMPOSE_SYSTEM

    assert "ĐO ĐƯỢC" in _DECOMPOSE_SYSTEM
    assert "CEO nêu tiêu chí" in _DECOMPOSE_SYSTEM
