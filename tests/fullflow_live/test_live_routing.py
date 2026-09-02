"""Nhóm A — định tuyến từ tin nhắn CEO, model thật.

Mỗi case: một `trigger()` qua đúng seam intake thật, rồi assert bản ghi định tuyến
(`route_json`) — tầng quyết định — chứ không đoán mò từ hình dạng DAG. Assert vào route
record là điều khiến các case này chịu được tính bất định của model: ta hỏi "bộ định
tuyến quyết gì và vì lý do nào", không hỏi "model viết ra chữ gì".

A3/A4 dừng ở preview rồi huỷ: routing là thứ cần chứng minh, còn việc THỰC THI một bước
ghi-ra-ngoài hay chạy shell đã có suite riêng. Một bộ test không bao giờ được gửi email
thật hay chạy shell thật chỉ để chứng minh nó định tuyến đúng.
"""

from __future__ import annotations

import pytest


def _assign(run, text: str) -> dict:
    """Trigger một đề rồi trả bản ghi định tuyến của task vừa tạo."""
    reply = run.h.trigger(text)
    rows = run.h.task_rows()
    assert rows, f"đề này phải tạo ra task, nhưng không có. reply={reply[:200]!r}"
    return {"reply": reply, "task_id": rows[-1]["id"], "route": run.route(rows[-1]["id"])}


# --- A1/A2: hai lane cơ bản, trọn vòng đời ------------------------------------------


@pytest.mark.live_slow
def test_a1_a_short_lookup_brief_runs_the_fast_lane_end_to_end(live_run):
    """Lane nhanh, từ tin nhắn tới sản phẩm giao được.

    Đây là case đắt nhất nhưng cũng là case duy nhất chứng minh cả chuỗi thật sự chạy
    được bằng model thật: định tuyến → sprint → giao hàng."""
    run = live_run()
    out = _assign(run, "Giá bán lẻ hiện tại của iPhone 17 Pro và Galaxy S26 Ultra ở VN?")
    assert out["route"].get("mode") == "sprint", out["route"]
    assert out["route"].get("source") == "heuristic", out["route"]

    run.h.pump(ticks=4)
    steps = run.h.step_rows(out["task_id"])
    assert [s["step_type"] for s in steps] == ["sprint"], steps
    assert run.cost() > 0, "một chuyến chạy model thật phải ghi lại chi phí thật"


@pytest.mark.live_slow
def test_a2_a_multi_part_brief_with_no_surviving_boundary_comes_back_as_a_sprint(live_run):
    """Ba đầu việc, trong đó phần khảo sát liệt kê 4 đối thủ → bộ đoán đẩy sang đội và
    model dựng kế hoạch nhiều bước. Trước đây kế hoạch dạng toả ra/gộp lại giữ được lane
    đội; bench đã loại dạng đó (đội thắng judge mù 4/12), nên nguồn song song không còn
    là ranh giới. Không có người soát được xin, không có công cụ nhạy ⇒ cổng dạng đội
    trả về sprint và ghi đúng lý do — khác `test_a7` ở chỗ đường đi ở đây là XÁC ĐỊNH:
    phải qua decompose rồi mới bị cổng dạng đội trả về (`source="shape"`)."""
    run = live_run()
    out = _assign(run, (
        "Làm giúp anh 3 việc: (1) khảo sát 4 đối thủ giao đồ ăn: GrabFood, ShopeeFood, "
        "Baemin, Gojek về phí và khuyến mãi, (2) viết bản tóm tắt định vị sản phẩm "
        "của mình, (3) dựng kế hoạch truyền thông 2 tuần tới."
    ))
    route = out["route"]
    assert (route.get("mode"), route.get("source")) == ("sprint", "shape"), route
    assert "shape" not in route, route

    steps = run.h.step_rows(out["task_id"])
    assert [s["step_type"] for s in steps] == ["sprint"], steps


# --- A3/A4: rào an toàn — định tuyến rồi DỪNG ---------------------------------------


@pytest.mark.parametrize(
    ("case", "brief"),
    [
        ("external_write", "Tổng hợp báo giá rồi gửi email cho khách hàng Anh Minh."),
        ("shell", "Clone repo github.com/org/demo về rồi chạy test suite giúp anh."),
    ],
)
def test_a3_a4_a_guarded_brief_never_takes_the_fast_lane(live_run, case, brief):
    """Bốn loại rào an toàn không bao giờ được chạy sprint, kể cả khi CEO ép.

    Lý do rào cứng: `_build_sprint_task` đóng cứng `external_write=False`/`needs_shell=
    False`, trong khi lane đội giữ review bắt buộc cho mọi bước ghi-ra-ngoài. Sprint hoá
    một đề như thế là lặng lẽ bỏ qua lượt duyệt.

    Case dừng ngay sau khi định tuyến — không pump. Không có bước nào được chạy, nên
    không có email nào được gửi và không có shell nào được chạy từ một bộ test."""
    run = live_run()
    out = _assign(run, brief)
    assert out["route"].get("mode") == "team", (case, out["route"])
    assert out["route"].get("source") == "refusal", (case, out["route"])
    assert not any(
        s["status"] == "running" for s in run.h.step_rows(out["task_id"])
    ), "case rào an toàn phải dừng trước khi chạy bất cứ bước nào"


# --- A5/A6: tiền tố của CEO thắng bộ đoán -------------------------------------------


def test_a5_the_sprint_prefix_overrides_a_team_shaped_brief(live_run):
    """CEO gõ `sprint:` là một quyết định, không phải gợi ý — bộ đoán phải nhường."""
    run = live_run()
    out = _assign(run, (
        "sprint: khảo sát 5 công cụ quản lý dự án, viết tóm tắt so sánh, và dựng "
        "kế hoạch triển khai 2 tuần"
    ))
    assert out["route"].get("mode") == "sprint", out["route"]
    assert out["route"].get("source") == "prefix", out["route"]


def test_a6_the_team_prefix_is_never_downgraded(live_run):
    """Chiều ngược lại: `team:` không bị lưới đỡ downgrade kéo về sprint.

    Lưới downgrade tồn tại để sửa phán đoán của BỘ ĐOÁN, không phải để sửa quyết định
    của CEO — kể cả khi kế hoạch hoá ra suy biến còn một bước.

    Đề phải nằm TRONG lĩnh vực của dàn diễn viên (domain pack `pm`) và tránh mọi chữ
    trùng với `company_activity` ("hoạt động", "tuần/ngày qua"). Hai bản trước chết ở
    tầng phân loại chứ không tới được tầng định tuyến: bản dùng "tóm tắt ... tin tức
    ... tuần này" bị đọc thành câu hỏi tình hình công ty, bản dùng đề marketing xe bị
    chính agent từ chối vì ngoài lĩnh vực. Cả hai đều là đo nhầm tầng."""
    run = live_run()
    out = _assign(run, "team: viết giúp anh bản mô tả phạm vi cho tính năng đăng nhập")
    assert out["route"].get("mode") == "team", out["route"]
    assert out["route"].get("source") == "prefix", out["route"]


# --- A7/A8: hai lưới đỡ còn lại -----------------------------------------------------


@pytest.mark.live_slow
def test_a7_a_one_person_brief_ends_up_on_the_fast_lane(live_run):
    """Lưới đỡ team→sprint. Đề vượt ngưỡng cấu trúc nên bộ đoán đẩy sang team, nhưng
    kế hoạch model dựng ra lại chỉ ra một người → hạ về sprint.

    Assert theo TẬP CHẤP NHẬN vì ba đường đều đúng: bộ đoán thấy ngay đây là việc một
    người (`heuristic`), phải qua decompose mới lộ (`downgrade`), hoặc kế hoạch nhiều
    người nhưng không có ranh giới nào của các dạng đội còn lại (`shape`). Điều phải đúng là
    lane cuối cùng — sprint — chứ không phải model đi đường nào."""
    run = live_run()
    out = _assign(run, (
        "Anh cần một bản tóm tắt ngắn về tình hình giá thép xây dựng trong nước "
        "tháng này, kèm nhận định xu hướng tháng tới, gửi lại anh trong hôm nay nhé."
    ))
    route = out["route"]
    assert route.get("mode") == "sprint", route
    assert route.get("source") in {"downgrade", "heuristic", "shape"}, route


def test_a8_too_many_entities_still_ends_as_a_sprint_since_breadth_is_no_boundary(live_run):
    """Quá nhiều thực thể vẫn là tín hiệu CẤU TRÚC cho bộ đoán (đẩy sang đội để model
    dựng kế hoạch), nhưng kế hoạch đó chỉ có thể là toả ra/gộp lại — dạng đội bench đã
    loại — nên cổng dạng đội trả về sprint. Phủ 12 mục là việc của sprint:
    `sprint_query_budget` co giãn theo số thực thể liệt kê (có trần), không còn là
    ngân sách phẳng 6 slot từng khiến 12 mục "chắc chắn không đủ"."""
    run = live_run()
    out = _assign(run, (
        "So sánh giúp anh 12 sàn TMĐT: Shopee, Lazada, Tiki, Sendo, TikTok Shop, "
        "Amazon, eBay, Alibaba, Taobao, Coupang, Rakuten, Mercado Libre."
    ))
    route = out["route"]
    assert (route.get("mode"), route.get("source")) == ("sprint", "shape"), route
    assert route.get("signals", {}).get("entities", 0) >= 8, route
    steps = run.h.step_rows(out["task_id"])
    assert [s["step_type"] for s in steps] == ["sprint"], steps
    # The step rows carry no routing flags; the stored step does.
    store = run.h.store()
    try:
        sprint_step = store.get_step(out["task_id"], steps[0]["step_id"])
    finally:
        store.close()
    assert sprint_step.needs_web, sprint_step
