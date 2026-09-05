"""A self-check finding the draft itself disproves must not send the step to rework.

Measured on the 2026-09-05 role scorecard: the reviewer failed a clean price-notice draft
with "thiếu 'áp dụng từ tháng sau'" while that exact phrase sat in the draft. Rework on a
finding like that can only damage the draft (the writer "adds" what is already there, or
rewrites around it). The filter lives in `review_failure_refutation`; this file pins that
`_run_self_check` actually applies it and that a REAL finding next to a refuted one still
fails the step.

No provider is touched — `LlmClient` is swapped for a canned verdict, same pattern as
`test_deterministic_step_check._fake_llm`.
"""

from __future__ import annotations

import json

from my_crew.agent.team_task_graph import default_team_task_deps

_DRAFT = (
    "Kính gửi quý khách,\n"
    "Từ ngày 01/10 bảng giá dịch vụ điều chỉnh tăng 5%. Mức giá mới áp dụng từ tháng sau "
    "cho toàn bộ gói đang dùng.\n"
    "Trân trọng."
)
_CRITERIA = "- nêu rõ thời điểm áp dụng\n- văn phong lịch sự"


def _deps(tmp_path):
    return default_team_task_deps(
        settings=None, step_title="Soạn email báo giá mới",
        data_dir=tmp_path, task_id="t1", step_seq=1,
    )


def _canned_verdict(monkeypatch, failures: list[str]):
    import my_crew.llm.client as client_mod

    class _Llm:
        def __init__(self, _settings):
            pass

        def complete(self, messages, **_kw):
            class _R:
                content = json.dumps(
                    {"passed": False, "failures": failures, "confidence": 0.8},
                    ensure_ascii=False,
                )
                cost_usd = 0.0

            return _R()

    monkeypatch.setattr(client_mod, "LlmClient", _Llm)


def test_a_finding_the_draft_disproves_is_dropped_and_the_step_passes(tmp_path, monkeypatch):
    _canned_verdict(monkeypatch, ["Thiếu câu 'áp dụng từ tháng sau' như tiêu chí yêu cầu"])
    passed, failures, _ = _deps(tmp_path).run_self_check(_DRAFT, _CRITERIA)
    assert passed is True
    assert failures == []


def test_a_real_finding_beside_a_disproved_one_still_fails_the_step(tmp_path, monkeypatch):
    real = "Thiếu lời cảm ơn khách hàng ở cuối thư"
    _canned_verdict(
        monkeypatch, ["Không thấy cụm 'áp dụng từ tháng sau' trong thư", real],
    )
    passed, failures, _ = _deps(tmp_path).run_self_check(_DRAFT, _CRITERIA)
    assert passed is False
    assert failures == [real]


def test_a_missing_claim_the_draft_confirms_is_kept(tmp_path, monkeypatch):
    """The filter only fires when the quoted phrase IS in the draft — a correct
    "missing" finding keeps failing the step exactly as before."""
    _canned_verdict(monkeypatch, ["Thiếu cụm 'liên hệ tổng đài' để khách hỏi thêm"])
    passed, failures, _ = _deps(tmp_path).run_self_check(_DRAFT, _CRITERIA)
    assert passed is False
    assert failures == ["Thiếu cụm 'liên hệ tổng đài' để khách hỏi thêm"]
