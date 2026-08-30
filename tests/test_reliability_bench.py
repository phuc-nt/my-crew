"""`reliability` bench: đo độ ổn định của intake, và chứng minh nó ĐO ĐƯỢC.

Cùng kỷ luật với `test_routing_bench`: bảng delta chỉ có giá trị nếu nó ĐỔI khi hành vi
đổi. Nên bài cốt lõi ở đây không assert vào một con số — nó tiêm một intake bấp bênh
thật rồi khẳng định comparator nhìn thấy. Assert vào con số cụ thể sẽ xanh y hệt kể cả
khi `compare_reliability` trả rỗng cho mọi thứ.

Toàn bộ file chạy offline: `bench_case` nhận tham số `intake` tiêm được, nên không bài
nào ở đây tốn một lời gọi model. Đó là điều kiện thiết kế — một bộ test chỉ chạy được
khi có key thì sẽ không ai chạy nó.
"""

from __future__ import annotations

import pytest

import my_crew.bench.reliability_bench as bench
from my_crew.bench.brief_suite import NOTE_TAKING, STREAMING_SERVICES


class _Plan:
    """Đủ hình dạng `SprintPlan` cho những gì bench đọc, không hơn."""

    def __init__(self, goal: str, acceptance: str, assigned_to: str = "writer",
                 needs_web: bool = True) -> None:
        self.goal = goal
        self.acceptance = acceptance
        self.assigned_to = assigned_to
        self.needs_web = needs_web


def _healthy(brief: str, _staff, pic_requested: str = ""):
    """Intake khoẻ: luôn rút gọn được, không bao giờ rơi fail-open."""
    return _Plan(goal=f"Rút gọn: {brief[:20]}", acceptance="Có đủ mục"), 0.0


def _always_fallback(brief: str, _staff, pic_requested: str = ""):
    """Intake hỏng hẳn: mọi lượt đều rơi về kế hoạch nguyên văn đề, acceptance rỗng —
    đúng dấu vết `_fallback` để lại."""
    return _Plan(goal=brief.strip(), acceptance=""), 0.0


def _flaky(fail_every: int):
    """Intake lúc được lúc không, theo chu kỳ cố định để bài kiểm tra tất định."""
    state = {"n": 0}

    def _intake(brief: str, _staff, pic_requested: str = ""):
        state["n"] += 1
        if state["n"] % fail_every == 0:
            return _Plan(goal=brief.strip(), acceptance=""), 0.0
        return _Plan(goal=f"Rút gọn: {brief[:20]}", acceptance="Có đủ mục"), 0.0

    return _intake


# --- đo đúng thứ cần đo ---------------------------------------------------------------


def test_a_healthy_intake_scores_a_perfect_pass_rate():
    report = bench.run_suite((STREAMING_SERVICES,), k=5, intake=_healthy)
    case = report["cases"]["streaming_services"]
    assert case["pass_rate"] == 1.0, case
    assert case["flake"] is False, case


def test_an_intake_that_always_falls_open_scores_zero():
    """Fail-open KHÔNG nổ và KHÔNG làm test nào khác đỏ — nó chỉ lặng lẽ trả lại nguyên
    văn đề của CEO. Cả module này tồn tại để đúng chuyện đó thành một con số."""
    report = bench.run_suite((STREAMING_SERVICES,), k=5, intake=_always_fallback)
    case = report["cases"]["streaming_services"]
    assert case["pass_rate"] == 0.0, case
    assert case["flake"] is False, case  # hỏng ổn định vẫn là ổn định, không phải flake


def test_an_intermittent_intake_is_marked_flake():
    """Trục `flake` là con số v2 vứt đi: cùng một đề, cùng một bản, lúc được lúc không.
    pass_rate 0 hay 1 đều không phải flake — chỉ khoảng giữa mới là."""
    report = bench.run_suite((STREAMING_SERVICES,), k=4, intake=_flaky(fail_every=2))
    case = report["cases"]["streaming_services"]
    assert case["pass_rate"] == 0.5, case
    assert case["flake"] is True, case


def test_a_run_that_raises_is_counted_as_a_miss_and_keeps_its_reason():
    """Nổ hẳn khác fail-open: fail-open là đường đã thiết kế, nổ là ngoài dự kiến. Một
    bản làm intake nổ sạch không được phép trông giống một bản chỉ fail-open nhiều."""

    def _boom(_brief, _staff, pic_requested: str = ""):
        raise RuntimeError("model provider down")

    report = bench.run_suite((STREAMING_SERVICES,), k=3, intake=_boom)
    case = report["cases"]["streaming_services"]
    assert case["pass_rate"] == 0.0, case
    assert len(case["errors"]) == 3, case
    assert "model provider down" in case["errors"][0], case


def test_the_fallback_probe_needs_both_signals_not_just_a_short_goal():
    """`_is_fallback` đòi CẢ hai điều kiện. Một bản rút gọn tình cờ trùng đề mà vẫn có
    acceptance là intake THẬT, không phải fail-open — đếm nhầm nó sẽ thổi phồng tỉ lệ
    hỏng của mọi đề ngắn."""
    brief = "viết mô tả sản phẩm"
    assert bench._is_fallback(_Plan(goal=brief, acceptance=""), brief) is True
    assert bench._is_fallback(_Plan(goal=brief, acceptance="Có đủ mục"), brief) is False


# --- bảng delta có thật sự nhìn thấy thay đổi không -----------------------------------


def test_the_delta_table_sees_a_pass_rate_regression():
    """Bài cốt lõi. Baseline khoẻ, candidate bấp bênh → comparator PHẢI ra dòng
    `pass_rate`. Đây là bài duy nhất chứng minh cả mode này có ích."""
    baseline = bench.run_suite((STREAMING_SERVICES,), k=4, intake=_healthy)
    candidate = bench.run_suite((STREAMING_SERVICES,), k=4, intake=_flaky(fail_every=2))

    rows = bench.compare_reliability(baseline, candidate)
    fields = {r["field"] for r in rows}
    assert "pass_rate" in fields, rows
    assert "flake" in fields, rows
    row = next(r for r in rows if r["field"] == "pass_rate")
    assert row["baseline"] == 1.0 and row["candidate"] == 0.5, row


def test_the_delta_table_sees_an_assignee_change_even_when_the_rate_holds():
    """Một bản giao việc cho người khác mà vẫn "thành công" 5/5 là thay đổi hành vi cần
    người đọc nhìn thấy. Nếu chỉ so pass_rate thì nó tàng hình."""

    def _to_analyst(brief, _staff, pic_requested: str = ""):
        return _Plan(goal=f"Rút gọn: {brief[:20]}", acceptance="Có", assigned_to="analyst"), 0.0

    baseline = bench.run_suite((STREAMING_SERVICES,), k=3, intake=_healthy)
    candidate = bench.run_suite((STREAMING_SERVICES,), k=3, intake=_to_analyst)

    rows = bench.compare_reliability(baseline, candidate)
    assert [r["field"] for r in rows] == ["assignee_mode"], rows
    assert all(r["baseline"] == 1.0 for r in rows if r["field"] == "pass_rate")


def test_an_identical_pair_reports_no_difference():
    """Vế còn lại: bảng delta không được kêu khi không có gì đổi, nếu không mọi lần so
    bản đều là báo động giả."""
    report = bench.run_suite((STREAMING_SERVICES, NOTE_TAKING), k=3, intake=_healthy)
    assert bench.compare_reliability(report, report) == []


def test_comparing_two_different_format_versions_is_refused():
    with pytest.raises(ValueError, match="format_version"):
        bench.compare_reliability({"format_version": 1, "k": 5, "cases": {}},
                                  {"format_version": 2, "k": 5, "cases": {}})


def test_comparing_two_different_k_is_refused():
    """pass_rate của k=3 và k=5 khác mẫu số, nên 0.67 vs 0.60 là một dòng delta VÔ
    NGHĨA — nó phản ánh mẫu số chứ không phản ánh hành vi. Từ chối còn hơn báo sai."""
    with pytest.raises(ValueError, match="khác k"):
        bench.compare_reliability({"format_version": bench.FORMAT_VERSION, "k": 3, "cases": {}},
                                  {"format_version": bench.FORMAT_VERSION, "k": 5, "cases": {}})


def test_a_case_present_on_only_one_side_is_reported_not_dropped():
    """Bỏ im lặng một case chỉ một bên có là giấu đi đúng thay đổi lớn nhất: một đề được
    thêm vào hoặc bỏ khỏi bộ đo."""
    rows = bench.compare_reliability(
        {"format_version": bench.FORMAT_VERSION, "k": 5, "cases": {}},
        {"format_version": bench.FORMAT_VERSION, "k": 5, "cases": {"x": {"pass_rate": 1.0}}},
    )
    assert [r["case"] for r in rows] == ["x"]


# --- lớp định tuyến: ghim tất định, không chạy k lượt vô nghĩa -------------------------


def test_the_routing_layer_is_pinned_deterministic_not_sampled():
    """Vì sao mode này KHÔNG chạy lại định tuyến k lượt: nó thuần code, nên pass_rate sẽ
    bằng 1.0 ở mọi case, mọi bản, mãi mãi. Một trục không bao giờ tụt được thì không
    phải là trục. Thay bằng một khẳng định tất định rẻ tiền."""
    assert bench.routing_stable() is True


def test_the_bench_makes_no_model_calls_when_intake_is_injected(monkeypatch):
    """Bộ test này phải chạy được khi không có key, nếu không sẽ không ai chạy nó."""
    import my_crew.llm.client as client_mod

    def _boom(*_a, **_k):
        raise AssertionError("reliability bench offline test phải không gọi model")

    monkeypatch.setattr(client_mod.LlmClient, "complete", _boom, raising=False)
    report = bench.run_suite((STREAMING_SERVICES,), k=3, intake=_healthy)
    assert report["cases"]["streaming_services"]["pass_rate"] == 1.0


def test_the_cli_default_k_matches_the_module_default():
    """`run-sprint-benchmark.py` hard-codes `--k` mặc định thay vì import hằng số này,
    để `--help` và các mode offline chạy được cả khi package chưa import nổi. Cái giá là
    hai con số có thể trôi khỏi nhau — nên ghim lại ở đây.

    Trôi khỏi nhau thì baseline chốt bằng CLI và baseline chốt bằng API sẽ khác mẫu số,
    và `compare_reliability` từ chối so — hỏng lúc đang cần so, đúng lúc bất tiện nhất.
    """
    import re
    from pathlib import Path

    src = Path("scripts/run-sprint-benchmark.py").read_text(encoding="utf-8")
    m = re.search(r'"--k", type=int, default=(\d+)', src)
    assert m, "không tìm thấy khai báo --k trong script bench"
    assert int(m.group(1)) == bench.DEFAULT_K, (
        f"CLI mặc định k={m.group(1)} nhưng reliability_bench.DEFAULT_K={bench.DEFAULT_K}"
    )
