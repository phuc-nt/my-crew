"""Tiền tố ép chế độ của CEO phải sống sót qua lớp tách slot.

Bug thật, do bài live A5 bắt được: bộ tách slot đọc mô tả "việc cần giao cho đội" là
lời kể nên nó bỏ `sprint:` đi, và `assign_team_task` nhận một đề đã sạch tiền tố rồi
định tuyến lại bằng bộ đoán. Lệnh ép chế độ vì thế im lặng vô hiệu ở đúng bề mặt trò
chuyện mà nó sinh ra để phục vụ — không lỗi, không cảnh báo, chỉ là chạy sai làn.

Bài ở đây chạy offline vào đúng hàm vá, vì bắt lại lỗi này bằng model thật tốn ~100s và
vài cent mỗi lần chạy.
"""

from __future__ import annotations

import pytest

from my_crew.agent.ops_chat import _restore_mode_prefix


@pytest.mark.parametrize("mode", ["sprint", "team"])
def test_a_prefix_dropped_by_the_slot_extractor_is_put_back(mode):
    slots = _restore_mode_prefix(f"{mode}: khảo sát 5 đối thủ",
                                 {"brief": "khảo sát 5 đối thủ"})
    assert slots["brief"] == f"{mode}: khảo sát 5 đối thủ"


def test_a_prefix_the_extractor_kept_is_not_doubled():
    slots = _restore_mode_prefix("sprint: khảo sát 5 đối thủ",
                                 {"brief": "sprint: khảo sát 5 đối thủ"})
    assert slots["brief"] == "sprint: khảo sát 5 đối thủ"


def test_a_brief_with_no_prefix_is_left_alone():
    """Chỉ chép lại thứ CEO thật sự gõ. Suy diễn thêm ở đây là tự ép chế độ cho một
    đề mà CEO không hề ép."""
    slots = _restore_mode_prefix("khảo sát 5 đối thủ", {"brief": "khảo sát 5 đối thủ"})
    assert slots["brief"] == "khảo sát 5 đối thủ"


def test_other_slots_are_untouched():
    slots = _restore_mode_prefix("sprint: việc", {"brief": "việc", "room_id": "r1"})
    assert slots["room_id"] == "r1"


def test_a_command_with_no_brief_slot_is_untouched():
    """Tiền tố chỉ có nghĩa với `assign_team_task`. Gắn nó vào lệnh khác là bịa dữ liệu
    vào một slot không hiểu nó."""
    assert _restore_mode_prefix("sprint: xem chi phí", {"range": "7d"}) == {"range": "7d"}


def test_the_original_slots_dict_is_not_mutated():
    original = {"brief": "khảo sát"}
    _restore_mode_prefix("sprint: khảo sát", original)
    assert original == {"brief": "khảo sát"}


def test_the_restored_brief_routes_by_prefix_not_by_guess():
    """Vế kết: sau khi chép lại, bộ định tuyến phải ra `source="prefix"`.

    Đây mới là điều bài live đòi. Chỉ assert chuỗi có tiền tố thì vẫn xanh kể cả khi
    `strip_mode_prefix` đổi cú pháp và bộ định tuyến hết nhận ra nó."""
    from my_crew.bench.routing_bench import decide

    brief = _restore_mode_prefix(
        "sprint: khảo sát 5 đối thủ, viết tóm tắt định vị, và dựng kế hoạch truyền thông",
        {"brief": "khảo sát 5 đối thủ, viết tóm tắt định vị, và dựng kế hoạch truyền thông"},
    )["brief"]
    mode, source, _reason, _signals = decide(brief)
    assert (mode, source) == ("sprint", "prefix")


def test_a_prefix_still_cannot_lift_a_safety_rail():
    """Vá này chỉ khôi phục QUYỀN CHỌN LÀN. Nó không được biến thành đường vòng qua
    rào an toàn: đề ghi-ra-ngoài vẫn phải về team dù CEO có gõ `sprint:`."""
    from my_crew.bench.routing_bench import decide

    brief = _restore_mode_prefix(
        "sprint: tổng hợp báo giá rồi gửi email cho khách",
        {"brief": "tổng hợp báo giá rồi gửi email cho khách"},
    )["brief"]
    mode, source, _reason, _signals = decide(brief)
    assert (mode, source) == ("team", "refusal")
