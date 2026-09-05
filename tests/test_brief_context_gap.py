"""`brief_context_gap.unresolved_reference_gap` — đề tựa vào ngữ cảnh bộ máy không có
thì bị hỏi lại TRƯỚC khi tiêu tiền; đề tự đứng được thì đi tiếp nguyên vẹn."""

from __future__ import annotations

import pytest

from my_crew.agent.brief_context_gap import unresolved_reference_gap


@pytest.mark.parametrize("brief", [
    "Gửi báo cáo cho họ như lần trước nhé.",
    "làm lại cái đó như cũ",
    "nhắn bên đó là mai họp như mọi khi",
    "send it to them like last time",
])
def test_a_bare_back_reference_is_asked_back_as_a_question(brief):
    gap = unresolved_reference_gap(brief)
    assert gap, brief
    assert gap.endswith("?") or "?" in gap
    # Câu hỏi nêu đúng cụm bị bắt để CEO thấy vì sao bị chặn.
    assert "'" in gap and "ai" in gap and "nào" in gap


def test_the_longest_reference_wins_so_the_question_does_not_repeat_itself():
    gap = unresolved_reference_gap("gửi cho họ như lần trước")
    assert "'như lần trước'" in gap
    assert "'lần trước'" not in gap.replace("'như lần trước'", "")


@pytest.mark.parametrize("brief", [
    # Tên riêng: mỏ neo đủ để đi tiếp.
    "Gửi báo cáo doanh thu cho anh Minh như lần trước nhé.",
    # @mã nhân sự.
    "@secretary gửi báo cáo cho họ như lần trước",
    # Con số / link / mail.
    "gửi báo cáo tuần 36 cho họ như lần trước",
    "gửi cho họ file ở https://example.com/report như cũ",
    "gửi cho họ qua mail ceo@example.com như lần trước",
    # Liệt kê thực thể.
    "so sánh cho họ 4 sàn: Shopee, Lazada, Tiki, Sendo như lần trước",
    # Không có cụm quy chiếu nào.
    "Tóm tắt giúp anh 3 xu hướng chính của ngành bán lẻ VN năm nay",
    "",
])
def test_an_anchored_or_plain_brief_passes_through(brief):
    assert unresolved_reference_gap(brief) == ""


def test_a_long_brief_carries_its_own_context_even_with_a_back_reference():
    brief = (
        "như lần trước, soạn giúp anh bản tóm tắt tình hình kinh doanh tuần này gồm doanh "
        "thu, chi phí, số đơn, tỷ lệ hoàn, top sản phẩm bán chạy, và ba việc cần làm tuần "
        "sau, viết ngắn gọn dưới một trang"
    )
    assert len(brief.split()) > 25
    assert unresolved_reference_gap(brief) == ""


def test_ho_inside_another_word_is_not_a_reference():
    assert unresolved_reference_gap("lập danh sách họ tên nhân viên mới") == ""
    assert unresolved_reference_gap("tra cứu dòng họ Nguyễn ở Huế") == ""
