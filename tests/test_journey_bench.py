"""`journey` baseline: chốt số đo journey, và chứng minh comparator ĐO ĐƯỢC.

Bài khó nhất ở mode này không phải "có bắt được hồi quy không" mà là "có IM LẶNG khi
không có hồi quy không". Journey chạy qua model thật nên hai lượt không bao giờ giống
nhau; một comparator so bằng `!=` sẽ đỏ ở mọi lượt, và một bảng lúc nào cũng đỏ thì
không ai đọc — nó tệ hơn là không có bảng. Nên file này kiểm CẢ HAI VẾ với trọng lượng
ngang nhau: nhiễu phải im, hồi quy phải kêu.

Chạy offline hoàn toàn: dựng metric bằng tay, không boot fleet, không gọi model.
"""

from __future__ import annotations

import pytest

import my_crew.bench.journey_bench as bench


def _metric(name="j1", *, cost=0.010, wall=120.0, calls=10, state="done", lanes=None):
    return bench.make_metric(name, cost_usd=cost, wall_s=wall, llm_calls=calls,
                             terminal_state=state, lanes=lanes or {"sprint": 1})


def _report(*metrics, version="0.15.0"):
    return bench.build_baseline(list(metrics), version=version)


# --- vế IM LẶNG: nhiễu model không được thành báo động --------------------------------


def test_an_identical_pair_reports_no_difference():
    r = _report(_metric())
    assert bench.compare_journey(r, r) == []


@pytest.mark.parametrize("cost,wall,calls", [
    (0.0105, 126.0, 11),   # lệch ~5%
    (0.0130, 160.0, 12),   # lệch ~30% — vẫn trong dung sai
    (0.0090, 100.0, 9),    # lệch xuống
])
def test_ordinary_run_to_run_noise_stays_silent(cost, wall, calls):
    """Đây là bài giữ cho mode này DÙNG ĐƯỢC. Không có nó, ngưỡng có thể bị siết dần
    tới mức mọi lượt đều đỏ mà không bài nào phản đối."""
    base = _report(_metric(cost=0.010, wall=120.0, calls=10))
    cand = _report(_metric(cost=cost, wall=wall, calls=calls))
    assert bench.compare_journey(base, cand) == [], (cost, wall, calls)


def test_two_near_zero_costs_do_not_report_a_giant_percentage():
    """$0.0001 so với $0.0002 là "gấp đôi" nhưng chỉ nói lên rằng cả hai đều ~0. Không
    có sàn thì mọi journey rẻ đều báo động giả vĩnh viễn."""
    base = _report(_metric(cost=0.0001))
    cand = _report(_metric(cost=0.0002))
    fields = {r["field"] for r in bench.compare_journey(base, cand)}
    assert "cost_usd" not in fields


def test_a_step_count_wobble_inside_the_same_lane_stays_silent():
    """Lane so theo TẬP KHOÁ: chạy thêm một bước trong cùng lane là dao động bình
    thường; đổi sang lane khác mới là thay đổi kiến trúc."""
    base = _report(_metric(lanes={"sprint": 1}))
    cand = _report(_metric(lanes={"sprint": 3}))
    assert bench.compare_journey(base, cand) == []


# --- vế KÊU: hồi quy thật phải hiện ra ------------------------------------------------


def test_a_terminal_state_change_is_always_reported():
    """Trục rời rạc, không dung sai: `done` -> `stalled` là hồi quy dù chỉ một lần."""
    base = _report(_metric(state="done"))
    cand = _report(_metric(state="stalled"))
    rows = bench.compare_journey(base, cand)
    assert [r["field"] for r in rows] == ["terminal_state"], rows
    assert rows[0]["baseline"] == "done" and rows[0]["candidate"] == "stalled"


def test_a_cost_blowout_is_reported_with_its_percentage():
    base = _report(_metric(cost=0.010))
    cand = _report(_metric(cost=0.030))
    row = next(r for r in bench.compare_journey(base, cand) if r["field"] == "cost_usd")
    assert row["delta"] == "+200%", row


def test_a_runaway_llm_call_count_is_reported():
    """Vòng lặp thừa hiện ra ở số lời gọi TRƯỚC khi đủ lớn để lộ ở hoá đơn — nên trục
    này chặt hơn trục tiền."""
    base = _report(_metric(calls=10))
    cand = _report(_metric(calls=20))
    fields = {r["field"] for r in bench.compare_journey(base, cand)}
    assert "llm_calls" in fields


def test_switching_lane_is_reported():
    base = _report(_metric(lanes={"sprint": 1}))
    cand = _report(_metric(lanes={"team": 4}))
    row = next(r for r in bench.compare_journey(base, cand) if r["field"] == "lanes")
    assert row["baseline"] == ["sprint"] and row["candidate"] == ["team"], row


def test_a_journey_present_on_only_one_side_is_reported_not_dropped():
    """Bỏ im lặng một journey chỉ một bên có là giấu đi đúng thay đổi lớn nhất: một
    journey được thêm vào hoặc BIẾN MẤT khỏi bộ đo."""
    rows = bench.compare_journey(_report(_metric("j1")), _report(_metric("j2")))
    assert sorted(r["case"] for r in rows) == ["j1", "j2"], rows
    assert all(r["field"] == "journey" for r in rows), rows


def test_comparing_two_different_format_versions_is_refused():
    with pytest.raises(ValueError, match="format_version"):
        bench.compare_journey({"format_version": 1, "journeys": {}},
                              {"format_version": 2, "journeys": {}})


# --- hình dạng baseline ---------------------------------------------------------------


def test_the_baseline_records_which_version_it_was_cut_from():
    """Một file baseline không ghi bản của chính nó thì sau vài tháng không ai dám tin."""
    r = _report(_metric(), version="0.15.0")
    assert r["version"] == "0.15.0"
    assert r["format_version"] == bench.FORMAT_VERSION


def test_the_metric_keys_match_what_the_live_harness_prints():
    """`journey_budget` in ra `cost_usd=` và `wall_s=`. Baseline phải dùng ĐÚNG hai tên
    đó thì người đọc mới đối chiếu tay được giữa output test và file baseline."""
    m = bench.make_metric("j1", cost_usd=0.01, wall_s=1.0, llm_calls=1,
                          terminal_state="done")
    d = m.__dict__ if not hasattr(m, "_asdict") else m._asdict()
    assert "cost_usd" in bench.build_baseline([m], version="x")["journeys"]["j1"]
    assert "wall_s" in bench.build_baseline([m], version="x")["journeys"]["j1"]
    assert d["journey"] == "j1"


def test_every_row_uses_the_shared_case_key_the_printer_expects():
    """`_print_delta` trong scripts/run-sprint-benchmark.py là bảng CHUNG của mọi mode
    so sánh, và nó đọc `row['case']`. Bản đầu của module này đặt khoá là `journey`, nên
    `journey --compare` nổ KeyError đúng lúc có khác biệt để in — mà cặp giống nhau lại
    in "no differences" bình thường. Nghĩa là mode này trông vẫn chạy được cho tới đúng
    lần đầu tiên nó có việc để làm.

    Ghim ở đây thay vì sửa printer: docstring của printer nói rõ nó được dùng chung để
    các cột không trôi khỏi nhau giữa các mode.
    """
    base = _report(_metric(cost=0.010, state="done"))
    cand = _report(_metric(cost=0.050, state="stalled"))
    rows = bench.compare_journey(base, cand)
    assert rows, "cần có khác biệt thì bài này mới kiểm được gì"
    for row in rows:
        assert {"case", "field", "baseline", "candidate"} <= set(row), row
