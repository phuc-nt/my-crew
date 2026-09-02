"""`routing` bench: đo QUYẾT ĐỊNH của bộ định tuyến, và chứng minh nó ĐO ĐƯỢC.

Một bảng so sánh chỉ có giá trị nếu nó ĐỔI khi hành vi đổi. Test cốt lõi ở đây vì thế
không assert vào một con số cụ thể — nó chỉnh một ngưỡng thật của bộ định tuyến rồi
khẳng định bảng delta nhìn thấy. Assert vào con số cụ thể sẽ xanh y hệt kể cả khi hàm
compare trả về rỗng cho mọi thứ.
"""

from __future__ import annotations

import pytest

import my_crew.agent.sprint_intake as intake
import my_crew.bench.routing_bench as bench
from my_crew.bench.brief_suite import ALL_CASES, OVER_CAP, PREFIX_SPRINT, ROUTING_CASES

# `over_cap` cố ý nằm ở cả hai nhóm, nên bộ hợp nhất phải khử trùng theo tên —
# `run_suite` khoá theo `case.name` nên một đề lặp chỉ ra một dòng báo cáo.
_ALL = tuple({c.name: c for c in ROUTING_CASES + ALL_CASES}.values())


# --- quyết định đúng tầng ------------------------------------------------------------


def test_the_routing_group_covers_every_branch_the_router_can_take():
    """Nhóm 8 đề cũ đi cùng một nhánh (`sprint`/`heuristic`) vì chúng được chọn để đo
    CHI PHÍ. Một báo cáo định tuyến chỉ nhìn thấy được thay đổi ở nhánh nào nó có đề đi
    qua, nên nhóm routing phải phủ đủ."""
    report = bench.run_suite(ROUTING_CASES)
    sources = {c["source"] for c in report["cases"].values()}
    modes = {c["mode"] for c in report["cases"].values()}
    assert sources == {"refusal", "prefix", "heuristic"}, sources
    assert modes == {"sprint", "team"}, modes


def test_a_guarded_brief_is_refused_before_the_prefix_is_even_read():
    """Thứ tự thẩm quyền: rào an toàn đứng TRƯỚC tiền tố ép chế độ. Đảo lại là để CEO
    gõ `sprint:` gỡ được rào — đúng thứ rào sinh ra để chặn."""
    mode, source, reason, _ = bench.decide(
        "sprint: tổng hợp báo giá rồi gửi email cho khách"
    )
    assert (mode, source) == ("team", "refusal"), (mode, source, reason)


def test_a_prefix_beats_the_heuristic():
    report = bench.run_suite((PREFIX_SPRINT,))
    case = report["cases"]["prefix_sprint"]
    assert (case["mode"], case["source"]) == ("sprint", "prefix"), case


def test_signals_are_numbers_only_and_never_carry_the_brief():
    """Bản ghi định tuyến nằm cạnh outcome trong DB, nên nó phải rẻ và KHÔNG mang theo
    nội dung việc của CEO."""
    _, _, _, signals = bench.decide("So sánh Shopee, Lazada và Tiki về phí sàn")
    assert set(signals) == {"brief_len", "entities", "distinct_asks", "material_transform",
                            "independent_sources", "needs_independent_review",
                            "sensitive_tool"}
    assert all(isinstance(v, int) for v in signals.values()), signals


# --- tất định, và có thật sự nhìn thấy thay đổi không ---------------------------------


def test_the_suite_is_deterministic_across_repeats():
    """Bộ định tuyến thuần luật. Lệch giữa hai lượt nghĩa là có trạng thái ẩn, và khi
    đó mọi con số so bản phía sau đều vô nghĩa — nên nó nổ chứ không cảnh báo."""
    report = bench.run_suite(_ALL, repeats=3)
    assert set(report["cases"]) == {c.name for c in _ALL}


def test_the_delta_table_sees_a_threshold_change(monkeypatch):
    """Test cốt lõi: hạ ngưỡng thực thể xuống dưới số thực thể của `over_cap` phải làm
    bảng delta đổi.

    Chỉnh ngưỡng THẬT chứ không dựng hai dict giả: một hàm compare trả rỗng cho mọi
    thứ vẫn qua được bài kiểm tra bằng dict giả, mà đó chính là kiểu hỏng cần bắt."""
    baseline = bench.run_suite((OVER_CAP,))
    assert baseline["cases"]["over_cap"]["mode"] == "team"

    # Nới ngưỡng lên trên số thực thể của đề → đề hết lý do bị đẩy sang team.
    monkeypatch.setattr(intake, "_MAX_SPRINT_ENTITIES", 99)
    candidate = bench.run_suite((OVER_CAP,))

    rows = bench.compare_routing(baseline, candidate)
    fields = {r["field"] for r in rows}
    assert "mode" in fields, rows
    assert candidate["cases"]["over_cap"]["mode"] == "sprint", candidate


def test_an_identical_pair_reports_no_difference():
    """Vế còn lại của bài trên: bảng delta không được kêu khi không có gì đổi, nếu
    không thì mọi lần so bản đều là báo động giả."""
    report = bench.run_suite(_ALL)
    assert bench.compare_routing(report, report) == []


def test_comparing_two_different_format_versions_is_refused():
    with pytest.raises(ValueError, match="format_version"):
        bench.compare_routing({"format_version": 1, "cases": {}},
                              {"format_version": 2, "cases": {}})


def test_a_case_present_on_only_one_side_is_reported_not_dropped():
    """Bỏ im lặng một case chỉ một bên có là giấu đi đúng thay đổi lớn nhất: một đề
    được thêm vào hoặc bỏ đi khỏi bộ đo."""
    rows = bench.compare_routing(
        {"format_version": bench.FORMAT_VERSION, "cases": {}},
        {"format_version": bench.FORMAT_VERSION, "cases": {"x": {"mode": "sprint"}}},
    )
    assert [r["case"] for r in rows] == ["x"]


def test_the_bench_makes_no_model_calls(monkeypatch):
    """0 lời gọi model là điều kiện THIẾT KẾ: nó là thứ khiến mode này chạy được trong
    worktree của một tag cũ không có key. Ghim bằng cách làm mọi lời gọi nổ."""
    import my_crew.llm.client as client_mod

    def _boom(*_a, **_k):
        raise AssertionError("routing bench phải chạy được khi không có model")

    monkeypatch.setattr(client_mod.LlmClient, "complete", _boom, raising=False)
    report = bench.run_suite(_ALL)
    assert len(report["cases"]) == len(_ALL)


@pytest.mark.parametrize(
    "brief",
    [
        "@all khảo sát 5 công cụ quản lý dự án rồi tóm tắt",
        "@writer viết bài giới thiệu sản phẩm mới",
        "sprint: @all tổng hợp tin tức AI tuần này",
        "team: @analyst phân tích số liệu quý 3",
        "khảo sát 5 dịch vụ streaming và so sánh giá",
    ],
)
def test_the_bench_sees_the_same_signals_as_the_real_routing_path(brief):
    """`decide()` chép lại thứ tự quyết định của đường thật, nên nó phải chép ĐỦ.

    Bench từng bóc `sprint:`/`team:` mà quên bóc `@<id> `/`@all ` phía sau, nên
    `brief_len` của nó dài hơn đường thật đúng bằng tiền tố PIC. Không case nào trong
    bộ đề có tiền tố PIC nên chưa có quyết định nào lệch — nhưng `brief_len` là một
    trục ĐƯỢC SO và có ngưỡng, và cả module này tồn tại để một thay đổi ngưỡng hiện ra
    thành bảng delta. Một bản sao trôi đi thì đo chính bản sao đó.

    Bài này ghim ở tầng tín hiệu chứ không ở tầng lane: lệch tín hiệu xuất hiện TRƯỚC,
    còn lệch lane chỉ hiện ra khi độ lệch tình cờ vắt qua ngưỡng.
    """
    from my_crew.agent.ops_assign_team_task import parse_pic_prefix
    from my_crew.agent.sprint_intake import route_signals, strip_mode_prefix

    _forced, after_mode = strip_mode_prefix(brief)
    _pic, real_brief = parse_pic_prefix(after_mode)

    assert bench.decide(brief)[3] == route_signals(real_brief), brief
