"""`foreign_letters`: the character-level language-drift check used on advisor notes."""

import pytest

from my_crew.llm.vietnamese_text import foreign_letters


@pytest.mark.parametrize("text", [
    "",
    "Cùng một URL bị 403 Forbidden lặp lại 9 lần, nên đổi nguồn — không thử lại nữa.",
    "Giá 22.000.000₫ (≈ 850 €), xem https://vinfastauto.com/evo200?utm=1 & Q3/2026",
    "ĐÃ ĐỦ 3 DÒNG: Ổn, Ừ, Ỡ, Ẫ — mixed CASE with English words and code_names_v2",
    "Dấu “ngoặc kép”, ‘nháy đơn’, … và bullet • hay 5×3 ± 1 °C",
])
def test_vietnamese_and_ascii_text_is_clean(text):
    assert foreign_letters(text) == ""


@pytest.mark.parametrize("text, letters", [
    ("đã được truy lại 9 lần și de fiecare dată", "ș"),
    ("Este clar că página nu va mai răspunde, încearcă altă cale", "î"),
    ("Kết quả 正确 rồi", "正确"),
    ("Проверь источник", "Провеьистчнк"),
    ("Größe stimmt nicht", "öß"),
])
def test_letters_outside_the_vietnamese_alphabet_are_reported(text, letters):
    assert foreign_letters(text) == letters


def test_each_foreign_letter_is_reported_once_in_order():
    assert foreign_letters("ș ț ș ț î") == "șțî"
