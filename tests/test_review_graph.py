"""`review_graph.run_review_step` (M32): `perceive_locked -> review -> deliver` —
version-locked artifact read, one structured LLM call, verdict artifact write with the
rework-brief `result_text` carried alongside. Exercised with a fake `LlmClient` (no
real network/LLM call) and a real filesystem artifact round-trip via
`team_task_artifact`.
"""

from __future__ import annotations

import json

import pytest

import my_crew.llm.client as llm_client_mod
from my_crew.agent.review_graph import ReviewStepInput, run_review_step
from my_crew.agent.team_task_artifact import read_review_verdict_artifact, write_step_artifact
from my_crew.config.config_builders import build_settings_from_dict


class _FakeResult:
    def __init__(self, content: str, cost_usd: float | None = 0.02):
        self.content = content
        self.cost_usd = cost_usd


def _wire_llm(monkeypatch, *, verdict: dict, cost: float | None = 0.02):
    calls: list[list[dict]] = []

    class _FakeLlm:
        def __init__(self, _settings):
            pass

        def complete(self, messages):
            calls.append(messages)
            return _FakeResult(json.dumps(verdict, ensure_ascii=False), cost)

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)
    return calls


def _settings(tmp_path):
    return build_settings_from_dict({"data_dir": tmp_path})


def _input(**overrides) -> ReviewStepInput:
    base = dict(
        task_id="t1", graded_seq=1, verdict_seq=1, review_round=0, locked_version="attempt-1",
        acceptance="phải có số liệu cụ thể", step_title="draft báo cáo",
    )
    base.update(overrides)
    return ReviewStepInput(**base)


# --- happy path: passed verdict --------------------------------------------------------


def test_run_review_step_passed_writes_verdict_artifact(tmp_path, monkeypatch):
    write_step_artifact(
        tmp_path, "t1", 1, {"result_text": "báo cáo có 12 số liệu", "version": "attempt-1"},
    )
    calls = _wire_llm(monkeypatch, verdict={"passed": True, "failures": []})

    result = run_review_step(None, _settings(tmp_path), data_dir=tmp_path, review_input=_input())

    assert result["status"] == "done"
    assert result["passed"] is True
    assert result["failures"] == []
    assert result["delivered"] is True
    assert "đạt" in result["room_message"]
    assert len(calls) == 1

    artifact = read_review_verdict_artifact(tmp_path, "t1", 1, 0)
    assert artifact is not None
    assert artifact["passed"] is True
    assert artifact["reviewed_version"] == "attempt-1"
    assert artifact["round"] == 0


# --- needs_rework verdict: result_text carries prior output + failures ----------------


def test_run_review_step_needs_rework_verdict_artifact_carries_rework_brief(tmp_path, monkeypatch):
    write_step_artifact(
        tmp_path, "t1", 1, {"result_text": "báo cáo sơ sài", "version": "attempt-1"},
    )
    _wire_llm(
        monkeypatch,
        verdict={"passed": False, "failures": ["thiếu số liệu", "thiếu kết luận"]},
    )

    result = run_review_step(None, _settings(tmp_path), data_dir=tmp_path, review_input=_input())

    assert result["status"] == "done"
    assert result["passed"] is False
    assert result["failures"] == ["thiếu số liệu", "thiếu kết luận"]
    assert "cần sửa (2 lỗi)" in result["room_message"]

    artifact = read_review_verdict_artifact(tmp_path, "t1", 1, 0)
    assert artifact is not None
    assert artifact["passed"] is False
    rework_text = artifact["result_text"]
    assert "báo cáo sơ sài" in rework_text
    assert "thiếu số liệu" in rework_text
    assert "thiếu kết luận" in rework_text


# --- stale artifact: version mismatch never writes a verdict ---------------------------


def test_run_review_step_version_mismatch_is_stale_artifact_no_write(tmp_path, monkeypatch):
    write_step_artifact(
        tmp_path, "t1", 1, {"result_text": "báo cáo", "version": "attempt-STALE"},
    )
    calls = _wire_llm(monkeypatch, verdict={"passed": True, "failures": []})

    result = run_review_step(
        None, _settings(tmp_path), data_dir=tmp_path,
        review_input=_input(locked_version="attempt-CURRENT"),
    )

    assert result["status"] == "stale_artifact"
    assert result["passed"] is None
    assert result["delivered"] is False
    assert calls == []  # never calls the LLM against stale content
    assert read_review_verdict_artifact(tmp_path, "t1", 1, 0) is None


def test_run_review_step_missing_artifact_is_stale_artifact_no_write(tmp_path, monkeypatch):
    calls = _wire_llm(monkeypatch, verdict={"passed": True, "failures": []})

    result = run_review_step(None, _settings(tmp_path), data_dir=tmp_path, review_input=_input())

    assert result["status"] == "stale_artifact"
    assert calls == []
    assert read_review_verdict_artifact(tmp_path, "t1", 1, 0) is None


# --- round >=1: graded_seq (read) vs verdict_seq (write) split -------------------------


def test_run_review_step_round1_reads_rework_seq_writes_under_content_seq(tmp_path, monkeypatch):
    # Round-1 review reads the REWORK step's own artifact (seq=5) but the verdict file
    # is still filed under the ORIGINAL content step's seq (1) — see ReviewStepInput's
    # graded_seq/verdict_seq split.
    write_step_artifact(
        tmp_path, "t1", 5, {"result_text": "báo cáo đã sửa", "version": "rework-attempt-1"},
    )
    _wire_llm(monkeypatch, verdict={"passed": True, "failures": []})

    result = run_review_step(
        None, _settings(tmp_path), data_dir=tmp_path,
        review_input=_input(
            graded_seq=5, verdict_seq=1, review_round=1, locked_version="rework-attempt-1",
        ),
    )

    assert result["status"] == "done"
    # written under content step's seq (1), round 1 — NOT under the rework's own seq.
    artifact = read_review_verdict_artifact(tmp_path, "t1", 1, 1)
    assert artifact is not None
    assert read_review_verdict_artifact(tmp_path, "t1", 5, 1) is None


# --- parse_review_verdict error handling -------------------------------------------


def test_run_review_step_malformed_llm_json_raises_review_verdict_error(tmp_path, monkeypatch):
    write_step_artifact(tmp_path, "t1", 1, {"result_text": "x", "version": "attempt-1"})

    class _FakeLlm:
        def __init__(self, _settings):
            pass

        def complete(self, messages):
            return _FakeResult("not json at all")

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)

    from my_crew.agent.review_graph import ReviewVerdictError

    with pytest.raises(ReviewVerdictError):
        run_review_step(None, _settings(tmp_path), data_dir=tmp_path, review_input=_input())
