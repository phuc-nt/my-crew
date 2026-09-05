"""Ký tự ngoài bảng chữ tiếng Việt trong một đoạn văn model sinh ra.

Đo 2026-09-05 trên deepseek-v4-flash với suy luận tắt: 1/8 note advisor trượt sang
tiếng Romania giữa câu ("đã được truy lại 9 lần și de fiecare dată…"). Note đó đi
thẳng vào ngữ cảnh của agent đang làm việc, nên phải chặn bằng code — prompt đã yêu
cầu tiếng Việt rồi mà vẫn trượt.

Tiêu chí cố ý hẹp: chỉ nhìn KÝ TỰ, không đoán ngôn ngữ. Chữ Việt có dấu, ASCII (tiếng
Anh, URL, mã, số), dấu câu thường gặp đều hợp lệ. Bất kỳ chữ cái nào ngoài bảng đó
(ș ț î của Romania, Cyrillic, CJK…) là bằng chứng chắc chắn của trượt ngôn ngữ; một
câu tiếng Anh xen vào thì KHÔNG bắt được — đó là chuyện khác, bộ này không nhận."""

from __future__ import annotations

import re

_VIETNAMESE_LETTERS = (
    "aàáảãạăằắẳẵặâầấẩẫậbcdđeèéẻẽẹêềếểễệfghiìíỉĩịjklmnoòóỏõọôồốổỗộơờớởỡợpqrstu"
    "ùúủũụưừứửữựvwxyỳýỷỹỵz"
)
_ALLOWED = re.compile(
    "[" + _VIETNAMESE_LETTERS + _VIETNAMESE_LETTERS.upper()
    + r"0-9\s\x21-\x7e"          # ASCII printable: punctuation, digits, Latin letters
    + "–—‘’“”…•°×±₫€ "
    + "]"
)


def foreign_letters(text: str) -> str:
    """Every character of `text` outside the Vietnamese/ASCII set, in order, deduplicated.
    Empty string means the text is clean by this criterion."""
    seen: list[str] = []
    for ch in text:
        if ch.isalpha() and not _ALLOWED.match(ch) and ch not in seen:
            seen.append(ch)
    return "".join(seen)
