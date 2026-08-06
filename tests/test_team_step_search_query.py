"""Building the web-search query a team step actually sends.

The defect this replaces: the native work loop searched for the step TITLE verbatim, so
a plan-reader's label ("Tra cứu thông tin thị trường") went out as the query and came
back with nothing specific enough to satisfy the step's own acceptance criteria.
"""

from __future__ import annotations

from my_crew.agent.team_step_search_query import (
    MAX_QUERY_CHARS,
    MAX_QUERY_WORDS,
    build_search_query,
)

#: The brief that actually broke a live step: its own title, then the previous step's
#: markdown result_text folded in by the coordinator's retry. 50+ words, comfortably
#: under any character cap — which is exactly why a character cap did not catch it.
_BRIEF_THAT_BROKE_A_LIVE_STEP = (
    "Tôi sẽ tra cứu ngay các công cụ API Zalo OA tự động hóa.\n"
    "**Tra cứu web:** Zalo OA API tools third-party gateway marketing automation\n"
    "## Kết quả tra cứu\n"
    "### 1. Zalo Official API (Chính thức)\n"
    "| Thông tin | Chi tiết |\n"
    "|-----------|----------|\n"
    "| Giá | Miễn phí cho tài khoản OA đã xác thực, tính phí theo lượt tin ZNS |\n"
    "| Giới hạn | 500 tin nhắn mỗi ngày với OA chưa nâng cấp gói doanh nghiệp |\n"
)


def test_the_brief_specifics_reach_the_query_not_just_the_title():
    query = build_search_query(
        "Tra cứu thông tin thị trường",
        "Thị trường cà phê hòa tan Việt Nam quý 2 năm 2026",
    )
    assert "cà phê hòa tan" in query
    assert query.startswith("Tra cứu thông tin thị trường")


def test_a_title_alone_still_produces_a_query():
    assert build_search_query("giá cà phê hôm nay") == "giá cà phê hôm nay"


def test_nothing_to_search_for_returns_blank_so_the_caller_can_skip_the_call():
    assert build_search_query("", "") == ""
    assert build_search_query("   ", "\n\n") == ""


def test_handoff_boilerplate_headers_are_dropped():
    query = build_search_query(
        "Tổng hợp",
        "Kết quả các bước trước:\nDoanh thu Q1 tăng 12%\nGhi chú: nhớ trích nguồn",
    )
    assert "Doanh thu Q1" in query
    assert "Kết quả các bước trước" not in query
    assert "nhớ trích nguồn" not in query


def test_internal_content_delimiters_never_become_query_terms():
    query = build_search_query(
        "Phân tích",
        "<noi-dung-noi-bo label='ket-qua-buoc'>\n---\nSố liệu thật\n```\n",
    )
    assert "Số liệu thật" in query
    assert "<" not in query and "---" not in query and "```" not in query


def test_coordinator_guidance_in_the_brief_sharpens_the_next_attempts_query():
    # After a `retry_with_guidance` ruling the guidance is appended to the handoff —
    # it names exactly what the last search missed, so it belongs in the query.
    query = build_search_query(
        "Tra cứu",
        "CHỈ DẪN CỦA ĐIỀU PHỐI (lần trước chưa đạt):\nphải có số liệu 2026 từ GSO",
    )
    assert "số liệu 2026 từ GSO" in query
    # ...but the header line itself is noise to a search engine.
    assert "CHỈ DẪN CỦA ĐIỀU PHỐI" not in query


def test_a_long_brief_is_capped_by_word_count_not_character_length():
    """Brave rejects a `q` over 50 words with HTTP 422, which the search hook surfaces
    as "no results" — so an over-long query does not degrade, it returns nothing."""
    query = build_search_query("tiêu đề", " ".join(["từkhóa"] * 200))

    assert len(query.split()) <= MAX_QUERY_WORDS
    assert MAX_QUERY_WORDS <= 50  # the provider's hard limit; never raise past it
    assert not query.endswith("từkh")  # no mid-word fragment


def test_the_brief_that_broke_a_live_step_now_produces_a_sendable_query():
    """Regression for the production failure: a coordinator RETRY folded a prior step's
    markdown output into the brief, pushed the query past 50 words, and got 0 results —
    so the guided retry searched worse than the unguided first attempt did."""
    query = build_search_query(
        "Thu thập bảng giá và giới hạn tin nhắn của từng công cụ",
        _BRIEF_THAT_BROKE_A_LIVE_STEP,
    )

    assert len(query.split()) <= MAX_QUERY_WORDS
    assert len(query) <= MAX_QUERY_CHARS


def test_the_title_survives_the_cut_when_the_brief_overflows_it():
    """The cut keeps the HEAD, so an overflowing brief cannot push the words that
    identify the step out of the query and leave only a prior step's tail behind."""
    query = build_search_query(
        "bảng giá Zalo OA API", " ".join(["chitiếtthừa"] * 200),
    )

    assert query.startswith("bảng giá Zalo OA API")


def test_multiline_whitespace_is_squashed_to_a_single_line():
    query = build_search_query("a", "b\n\n\n   c   \n\td")
    assert query == "a b c d"
