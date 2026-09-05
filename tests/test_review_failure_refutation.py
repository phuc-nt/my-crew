"""A self-check finding that says a quoted phrase is missing, while the draft has it
verbatim, is the reviewer misreading its input — measured twice on the role bench
(clean price_increase_email: "thiếu 'áp dụng từ tháng sau'" on a draft carrying that
exact phrase). Rework on such a finding can only damage the draft, so it is dropped.

The filter must stay narrow: any finding the code cannot prove wrong is kept."""

from __future__ import annotations

from my_crew.llm.review_failure_refutation import (
    refuted_by_the_artifact,
    split_refuted_failures,
)

_DRAFT = (
    "Kính gửi quý khách,\n\nGiá gói Pro tăng từ 500.000đ lên 550.000đ, áp dụng từ tháng "
    "sau. Khách hàng hiện tại giữ giá cũ đến hết năm.\n\nTrân trọng."
)


def test_a_missing_claim_the_draft_disproves_is_refuted():
    assert refuted_by_the_artifact("Email thiếu mốc hiệu lực 'áp dụng từ tháng sau'", _DRAFT)
    # Quote style, case and inner whitespace do not matter — the phrase does.
    assert refuted_by_the_artifact('Không nêu "Áp dụng  từ tháng sau" cho khách', _DRAFT)


def test_a_missing_claim_the_draft_confirms_is_kept():
    assert not refuted_by_the_artifact("Thiếu 'thời hạn phản hồi' cho khách hàng", _DRAFT)


def test_a_critique_that_quotes_a_present_phrase_is_kept():
    """No absence marker: the reviewer is judging the phrase, not denying it exists."""
    assert not refuted_by_the_artifact("Cụm 'áp dụng từ tháng sau' quá mơ hồ, cần ngày cụ thể",
                                       _DRAFT)


def test_a_finding_without_a_quote_is_kept():
    assert not refuted_by_the_artifact("Thiếu mốc hiệu lực của mức giá mới", _DRAFT)


def test_two_quotes_with_one_really_missing_is_kept():
    assert not refuted_by_the_artifact(
        "Thiếu 'áp dụng từ tháng sau' và 'lý do tăng giá'", _DRAFT,
    )


def test_split_keeps_order_and_partitions():
    kept, refuted = split_refuted_failures(
        ["Thiếu 'lý do tăng giá'", "Không có 'áp dụng từ tháng sau'", "Giọng văn khô"],
        _DRAFT,
    )
    assert kept == ["Thiếu 'lý do tăng giá'", "Giọng văn khô"]
    assert refuted == ["Không có 'áp dụng từ tháng sau'"]
