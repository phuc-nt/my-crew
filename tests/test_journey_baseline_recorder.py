"""Bộ ghi baseline của live suite: ghi ĐÚNG cái đã xảy ra, và không ghi khi chưa biết.

File này chạy OFFLINE dù thứ nó kiểm nằm trong `tests/fullflow_live/`. Cố ý: bộ ghi chỉ
chạy sau một lượt live tốn tiền và mất ~5 phút, nên một lỗi trong nó chỉ lộ ra ở đúng lúc
đắt nhất. Ở đây dựng payload bằng tay nên mọi nhánh kiểm được miễn phí.

Nhập `conftest` như một module thường — nó không cần fixture nào của pytest để chạy hai
hàm thuần này.
"""

from __future__ import annotations

import json

import pytest

from tests.fullflow_live.conftest import BASELINE_OUT_ENV, JourneyBudget
from tests.fullflow_live.conftest import _record_baseline as record
from tests.fullflow_live.conftest import _terminal_state as terminal_state


def _status(state: str, steps: list[dict], calls: int = 0) -> dict:
    return {"state": {"status": state}, "steps": steps,
            "cost": {"steps": [{} for _ in range(calls)]}}


# --- terminal_state: "xong" và "đang chờ người" là hai kết cục khác nhau ---------------


def test_a_task_whose_own_row_reached_a_terminal_value_reports_that_value():
    assert terminal_state(_status("done", [{"status": "done"}])) == "done"


def test_a_task_parked_on_a_human_is_not_recorded_as_plain_open():
    """`is_settled` cho task xong theo HAI đường độc lập: row của task đạt giá trị cuối,
    HOẶC mọi bước đỗ lại chờ người trong khi row vẫn là `open`. J1/J2 đi đường thứ hai.

    Ghi thẳng `state.status` sẽ ra `open` cho một journey ĐÃ kết thúc — và rồi một bản
    sau sửa cho row task nói `done` sẽ hiện ra như hồi quy trong khi nó là bản vá.
    """
    assert terminal_state(_status("open", [{"status": "needs_decision"}])) == "parked:open"


def test_a_task_still_running_is_not_called_settled():
    assert terminal_state(_status("open", [{"status": "running"}])) == "open"


def test_a_task_with_no_steps_at_all_is_not_called_parked():
    """`all()` trên danh sách rỗng là True. Không chặn thì một task chưa có bước nào sẽ
    được ghi là "đã đỗ chờ người" — đúng loại đúng-một-cách-rỗng tuếch mà một file
    baseline không được phép chứa."""
    assert terminal_state(_status("open", [])) == "open"


# --- ghi ra file: chỉ ghi khi được bảo, chỉ ghi cái quan sát được ----------------------


def test_nothing_is_written_when_the_env_var_is_unset(tmp_path, monkeypatch):
    """Một lượt live thường KHÔNG được ghi đè baseline đã commit. Nếu ghi, "so với
    baseline" lặng lẽ thành "so với lượt chạy gần nhất" và không bao giờ đỏ được nữa."""
    monkeypatch.delenv(BASELINE_OUT_ENV, raising=False)
    b = JourneyBudget("j")
    b.note_cost(0.01, _status("done", [{"status": "done", "step_type": "sprint"}], calls=1))
    record(b, 1.0)
    assert list(tmp_path.iterdir()) == []


def test_a_journey_that_never_saw_a_status_contributes_no_row(tmp_path, monkeypatch):
    """Các case control (x2b, X4b…) không có task nào làm chủ thể. Ghi một dòng giữ chỗ
    cho chúng là đặt một con số bịa vào đúng file mà cả nhiệm vụ của nó là để tin."""
    out = tmp_path / "bl.json"
    monkeypatch.setenv(BASELINE_OUT_ENV, str(out))
    b = JourneyBudget("j_control")
    b.note_cost(0.0)  # không kèm status
    record(b, 5.0)
    assert not out.exists()


def test_each_journey_appends_instead_of_replacing_the_file(tmp_path, monkeypatch):
    """Ghi dồn từng case thay vì ghi một lần cuối phiên: một suite chết giữa chừng vẫn
    để lại những journey ĐÃ xong. Baseline thiếu case thì trung thực và lộ rõ (hiện thành
    dòng một-bên trong bảng delta); mất cả lượt chạy 20 phút trả tiền thì không."""
    out = tmp_path / "bl.json"
    monkeypatch.setenv(BASELINE_OUT_ENV, str(out))
    for name in ("j1", "j2"):
        b = JourneyBudget(name)
        b.note_cost(0.01, _status("done", [{"status": "done", "step_type": "sprint"}], calls=2))
        record(b, 10.0)
    assert sorted(json.loads(out.read_text())["journeys"]) == ["j1", "j2"]


def test_llm_calls_counts_captures_not_steps(tmp_path, monkeypatch):
    """Một bước có thể gọi model nhiều lần (retry, review). Đếm bước sẽ giấu đúng thứ
    trục này sinh ra để bắt: vòng lặp thừa."""
    out = tmp_path / "bl.json"
    monkeypatch.setenv(BASELINE_OUT_ENV, str(out))
    b = JourneyBudget("j")
    b.note_cost(0.01, _status("done", [{"status": "done", "step_type": "sprint"}], calls=4))
    record(b, 10.0)
    assert json.loads(out.read_text())["journeys"]["j"]["llm_calls"] == 4


def test_the_recorded_file_round_trips_through_the_comparator(tmp_path, monkeypatch):
    """Bộ ghi và bộ so phải nói cùng một schema. Lệch thì lỗi chỉ lộ ở lần so bản SAU —
    lúc baseline cũ đã commit và không cắt lại được nếu không trả tiền chạy lại."""
    from my_crew.bench.journey_bench import compare_journey

    out = tmp_path / "bl.json"
    monkeypatch.setenv(BASELINE_OUT_ENV, str(out))
    b = JourneyBudget("j")
    b.note_cost(0.01, _status("done", [{"status": "done", "step_type": "sprint"}], calls=2))
    record(b, 10.0)
    doc = json.loads(out.read_text())
    assert compare_journey(doc, doc) == []


@pytest.mark.parametrize("field", ["format_version", "version", "journeys"])
def test_the_file_carries_the_keys_the_comparator_requires(tmp_path, monkeypatch, field):
    out = tmp_path / "bl.json"
    monkeypatch.setenv(BASELINE_OUT_ENV, str(out))
    b = JourneyBudget("j")
    b.note_cost(0.01, _status("done", [{"status": "done", "step_type": "sprint"}]))
    record(b, 1.0)
    assert field in json.loads(out.read_text())
