"""v78 Phase 1: bộ định tuyến nói được vì sao, và câu trả lời cụt không bị đổ oan.

Hai mối lo tách rời nhưng cùng một gốc — "hệ thống biết mà không nói ra":

  1. Cắt cụt (`finish_reason == "length"`) làm hỏng JSON y hệt model viết bậy. Trước
     đây hai ca đó không phân biệt được, nên vòng thử lại nhắc "JSON của bạn hỏng" và
     model viết lại đúng kế hoạch quá dài đó — thử lại y nguyên thì hỏng y nguyên.
  2. Bản ghi định tuyến đã có từ v77 nhưng chưa mặt nào đọc ra, nên CEO không biết
     việc của mình đi đường nào, càng không biết vì sao.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import my_crew.agent.ops_assign_team_task as mod
import my_crew.agent.sprint_intake as intake_mod
import my_crew.runtime.company as company_mod
from my_crew.agent.sprint_intake import render_route_reason
from my_crew.llm.client import LlmResult


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


def _result(content: str, finish_reason: str = "") -> LlmResult:
    return LlmResult(content=content, model="m", prompt_tokens=1, completion_tokens=1,
                     cost_usd=0.001, finish_reason=finish_reason)


# --- LlmResult.truncated -------------------------------------------------------------


@pytest.mark.parametrize(
    ("finish_reason", "expected"),
    [("length", True), ("stop", False), ("tool_calls", False), ("", False)],
)
def test_truncated_reads_only_the_length_stop_reason(finish_reason, expected):
    assert _result("{}", finish_reason).truncated is expected


def test_finish_reason_defaults_to_not_truncated():
    """Mọi chỗ dựng LlmResult cũ (test, double) không truyền trường này — chúng phải
    tiếp tục chạy và báo "không cụt", chứ không nổ vì thiếu tham số."""
    assert LlmResult(content="x", model="m", prompt_tokens=0, completion_tokens=0,
                     cost_usd=None).truncated is False


# --- decompose: cụt thì bảo model NGẮN LẠI, không bảo nó "JSON hỏng" -----------------


def test_a_truncated_decompose_retries_asking_for_a_shorter_plan(monkeypatch):
    """Đây là điểm mấu chốt: prompt thử lại phải mang lý do THẬT.

    Nếu vòng lặp coi thân cụt là JSON hỏng, nó nhắc model sửa cú pháp — và model viết
    lại đúng kế hoạch quá dài đó. Thử lại giống hệt thì hỏng giống hệt.
    """
    retry_errors: list[str] = []
    good = ('{"pic_id": "agent-a", "steps": [{"step_id": "s1", "title": "làm việc",'
            ' "assigned_to": "agent-a", "deps": [], "acceptance": "xong"}]}')
    bodies = iter([_result('{"pic_id": "agent-a", "steps": [{"step_i', "length"),
                   _result(good, "stop")])

    def _build(*, brief, staff, retry_error, pic_requested):
        retry_errors.append(retry_error)
        return [{"role": "user", "content": brief}]

    monkeypatch.setattr("my_crew.llm.team_task_prompt.build_team_decompose_messages", _build)
    monkeypatch.setattr(mod, "_build_llm",
                        lambda: (SimpleNamespace(complete=lambda *a, **k: next(bodies)), None))

    task, _cost = mod._decompose_with_retries("làm một việc nhỏ", [("agent-a", "content")])

    assert len(task.steps) == 1
    # Lượt đầu không có lỗi trước đó; lượt hai phải nói đúng nguyên nhân.
    assert retry_errors[0] == ""
    assert "cắt cụt" in retry_errors[1] and "NGẮN GỌN" in retry_errors[1]


def test_a_truncated_decompose_does_not_burn_a_parse_attempt(monkeypatch):
    """Thân cụt không được đi vào `parse_decomposed_task` — parse nó chỉ sinh ra một
    thông báo lỗi sai sự thật, mà lỗi đó lại là thứ dẫn dắt lượt thử lại sau."""
    parsed: list[str] = []
    real_parse = mod.parse_decomposed_task

    def _spy(raw):
        parsed.append(raw)
        return real_parse(raw)

    good = ('{"pic_id": "agent-a", "steps": [{"step_id": "s1", "title": "làm việc",'
            ' "assigned_to": "agent-a", "deps": [], "acceptance": "xong"}]}')
    bodies = iter([_result("{cụt", "length"), _result(good, "stop")])
    monkeypatch.setattr(mod, "parse_decomposed_task", _spy)
    monkeypatch.setattr("my_crew.llm.team_task_prompt.build_team_decompose_messages",
                        lambda **kw: [{"role": "user", "content": "x"}])
    monkeypatch.setattr(mod, "_build_llm",
                        lambda: (SimpleNamespace(complete=lambda *a, **k: next(bodies)), None))

    mod._decompose_with_retries("làm một việc nhỏ", [("agent-a", "content")])

    assert parsed == [good]


# --- sprint intake: cụt thì fail-open với ĐÚNG lý do --------------------------------


def test_a_truncated_intake_fails_open_naming_truncation(monkeypatch, caplog):
    monkeypatch.setattr(mod, "_build_llm",
                        lambda: (SimpleNamespace(
                            complete=lambda *a, **k: _result('{"goal": "so sá', "length")), None))

    with caplog.at_level("WARNING"):
        plan, _cost = intake_mod.sprint_intake("so sánh giá 3 dịch vụ",
                                               [("agent-a", "content")])

    # Fail-open giữ nguyên hợp đồng cũ: dùng nguyên văn đề của CEO.
    assert plan.goal == "so sánh giá 3 dịch vụ"
    assert plan.assigned_to == "agent-a"
    assert "cắt cụt" in caplog.text
    # KHÔNG được đổ lỗi cho model viết JSON sai — nó viết đúng, chỉ là bị chặn giữa chừng.
    assert "JSON hỏng" not in caplog.text


def test_intake_still_reports_real_json_garbage_as_json_garbage(monkeypatch, caplog):
    """Lối cũ phải nguyên vẹn: thân đầy đủ mà hỏng thì vẫn là model viết bậy."""
    monkeypatch.setattr(mod, "_build_llm",
                        lambda: (SimpleNamespace(
                            complete=lambda *a, **k: _result("xin lỗi tôi không hiểu", "stop")),
                            None))

    with caplog.at_level("WARNING"):
        plan, _cost = intake_mod.sprint_intake("so sánh giá", [("agent-a", "content")])

    assert plan.goal == "so sánh giá"
    assert "JSON hỏng" in caplog.text


# --- render_route_reason -------------------------------------------------------------


def test_render_route_reason_names_the_mode_in_words_not_codes():
    line = render_route_reason({"mode": "sprint", "reason": "không có tín hiệu cần đội"})
    assert line == "Chế độ: chạy nhanh (1 người) (lý do: không có tín hiệu cần đội)"
    assert render_route_reason({"mode": "team", "reason": "đề quá dài (>1200 ký tự)"}) == (
        "Chế độ: cả đội (lý do: đề quá dài (>1200 ký tự))")


@pytest.mark.parametrize("route", [None, {}, {"mode": ""}, {"reason": "x"}])
def test_render_route_reason_is_empty_when_there_is_nothing_true_to_say(route):
    """Task trước v77 không có bản ghi route. In một dòng trống khó hiểu còn tệ hơn
    không in gì — nơi gọi dựa vào chuỗi rỗng để bỏ hẳn dòng này."""
    assert render_route_reason(route) == ""


def test_render_route_reason_drops_the_reason_clause_when_absent():
    assert render_route_reason({"mode": "sprint"}) == "Chế độ: chạy nhanh (1 người)"


# --- preview: CEO thấy lý do TRƯỚC khi bấm xác nhận ---------------------------------


def _wire_preview(monkeypatch):
    monkeypatch.setattr(mod, "_escalation_routable", lambda: True)
    monkeypatch.setattr(mod, "_staff_roster", lambda: [("agent-a", "content")])
    monkeypatch.setattr(
        company_mod, "load_company",
        lambda path=None: SimpleNamespace(name="", coordinator_id="coord-1",
                                          team_task_cap_usd=2.0,
                                          team_task_auto_confirm=False, autopilot=False),
    )
    from my_crew.agent.sprint_intake import SprintPlan

    monkeypatch.setattr(
        intake_mod, "sprint_intake",
        lambda brief, staff, pic="": (SprintPlan(goal="so sánh", acceptance="- xong",
                                                 assigned_to="agent-a", needs_web=True), 0.001))


def test_the_preview_tells_the_ceo_which_lane_and_why(monkeypatch):
    _wire_preview(monkeypatch)
    slots = {"brief": "so sánh giá 3 dịch vụ"}

    text = mod.preview_assign_team_task(slots)

    assert "Chế độ: chạy nhanh (1 người)" in text
    assert "lý do:" in text
    # Badge của composer vẫn dùng mã, không phải nhãn tiếng Việt — hai mặt khác nhau.
    assert slots["route_mode"] == "sprint"


def test_the_reason_line_sits_before_the_task_id_block(monkeypatch):
    """Mã việc + câu hỏi xác nhận là phần hành động; lý do là phần bối cảnh và phải
    đọc được trước khi mắt chạm tới nút bấm."""
    _wire_preview(monkeypatch)
    text = mod.preview_assign_team_task({"brief": "so sánh giá 3 dịch vụ"})

    assert text.index("Chế độ:") < text.index("Mã việc:")
