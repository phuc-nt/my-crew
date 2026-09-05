"""Cổng chặn đề TỰA VÀO NGỮ CẢNH MÀ HỆ THỐNG KHÔNG CÓ, trước khi tiêu một đồng nào.

Bối cảnh (đo thật, live b4, 3/3 lần trên deepseek-v4-flash): CEO nhắn "Gửi báo cáo cho
họ như lần trước nhé." — không có báo cáo nào, không có "họ" nào, không có "lần trước"
nào trong bộ máy này. Bộ phân loại ý định vẫn điền nguyên câu vào slot `brief`, intake
sprint thì viết lại thành mục tiêu nghe rất trôi ("gửi báo cáo cho nhóm người nhận theo
đúng danh sách như lần trước") và một hàng task được ghi xuống ở trạng thái planning.
Tức là bộ máy ĐOÁN rồi mới hỏi — ngược với hợp đồng: hỏi lại rẻ hơn hẳn chạy trọn một
chuyến rồi giao sai.

Prompt không đóng được lỗ này: cả prompt phân loại lẫn prompt intake đều đã dặn "bỏ
trống slot chưa rõ", model vẫn điền. Nên cổng này là CODE, tất định, chạy trước lượt
decompose/intake (không tốn model), và chỉ bắt đúng một hình dạng hẹp: đề có cụm
QUY CHIẾU NGƯỢC (họ, như lần trước, cái đó, ...) mà KHÔNG có bất kỳ mỏ neo nào để giải
nghĩa (không tên riêng, không @mã, không số, không link/mail, không liệt kê thực thể,
và ngắn). Đề dài hay có tên riêng thì vẫn đi tiếp — lúc đó "như lần trước" chỉ là
lời dẫn, phần việc còn lại tự đứng được.
"""

from __future__ import annotations

import re

#: Cụm quy chiếu ngược — đề dựa vào một chuyện đã xảy ra ở đâu đó ngoài bộ máy này.
#: So khớp trên chữ thường; giữ cả cụm (không phải từ đơn) để "họ" trong "họ tên" /
#: "dòng họ" hay "đó" trong "đó là" không bắt nhầm.
_BACK_REFERENCES: tuple[str, ...] = (
    "như lần trước", "giống lần trước", "như lần rồi", "như hôm trước", "như hôm qua",
    "như cũ", "như mọi khi", "như thường lệ", "như đã bàn", "như đã nói", "như đã thống nhất",
    "lần trước", "cái đó", "việc đó", "bên đó", "chỗ đó", "người đó", "mấy người đó",
    "bọn họ", "cho họ", "gửi họ", "với họ", "tới họ", "đến họ", "của họ",
    "cho anh ấy", "cho chị ấy", "cho cô ấy", "cho ổng", "cho bả",
    "like last time", "same as last time", "as before", "to them", "for them",
)

#: Mỏ neo giải nghĩa được: @mã nhân sự, con số, link, email.
_ANCHOR = re.compile(r"@\w+|\d|https?://|www\.|[\w.+-]+@[\w-]+\.\w+")

#: Đề dài hơn ngần này từ thì phần việc tự đứng được, cụm quy chiếu chỉ còn là lời dẫn.
_MAX_WORDS_FOR_GATE = 25


def _back_references(low: str) -> list[str]:
    found = [ref for ref in _BACK_REFERENCES if ref in low]
    # "như lần trước" đã chứa "lần trước" — chỉ giữ cụm dài nhất để câu hỏi không lặp.
    return [ref for ref in found if not any(ref != other and ref in other for other in found)]


def _has_proper_noun(brief: str) -> bool:
    """Một chữ viết hoa KHÔNG đứng đầu câu là tên riêng — mỏ neo đủ để đi tiếp."""
    for sentence in re.split(r"[.!?\n]+", brief):
        words = sentence.split()
        for word in words[1:]:
            stripped = word.strip("\"'“”‘’()[],;:")
            if stripped[:1].isupper():
                return True
    return False


def unresolved_reference_gap(brief: str) -> str:
    """"" khi đề tự đứng được; ngược lại là câu hỏi CEO cần trả lời trước khi giao.

    Câu hỏi nêu đúng những cụm bị bắt để CEO thấy vì sao bị chặn, và kết bằng dấu hỏi:
    đây là một câu HỎI LẠI, không phải một lỗi.
    """
    from my_crew.runtime.sprint_runner import listed_entities

    text = (brief or "").strip()
    if not text:
        return ""
    low = text.lower()
    refs = _back_references(low)
    if not refs:
        return ""
    if len(text.split()) > _MAX_WORDS_FOR_GATE:
        return ""
    if _ANCHOR.search(text) or _has_proper_noun(text) or listed_entities(text):
        return ""
    quoted = ", ".join(f"'{ref}'" for ref in refs)
    return (
        f"đề tựa vào chuyện mình chưa biết ({quoted}) — mình không có lịch sử đó để tra. "
        "CEO nói rõ giúp: đối tượng là ai, tài liệu/nội dung nào, làm theo cách nào "
        "(kênh, mẫu)? Mình sẽ giao ngay khi đủ ba ý đó."
    )
