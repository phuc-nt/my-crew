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


# -- rework rounds: the defect list outranks the draft ---------------------------------

def _rework_brief(draft: str, failures: list[str]) -> str:
    """A rework brief in its real shape, built by the same producer the runtime uses."""
    from my_crew.agent.review_graph import _rework_handoff_text

    return _rework_handoff_text(draft, failures)


def test_a_fix_round_searches_the_defects_not_the_draft_that_failed():
    """The point of the fix round: search what the reviewer said was MISSING.

    The brief is `prior draft + defect list`, and the draft is both longer and first,
    so plain document order spends the 44-word budget re-searching the text that had
    just been rejected — returning the sources that produced it. Measured on task
    51ad15207896, that put the defect list into only 3 of 7 rework queries.
    """
    query = build_search_query(
        "Khảo sát giải pháp langmem",
        _rework_brief(
            "LangMem là thư viện quản lý bộ nhớ. " + "nội dung nháp dài dòng " * 60,
            ["Thiếu 2 nhược điểm cụ thể của LangMem", "Chưa có nguồn cho số liệu"],
        ),
    )

    assert "nhược điểm" in query, "the reviewer's defect must reach the query"
    assert "nguồn" in query, "every defect must fit, not just the first"
    # Both defects precede any draft text — the draft may still fill the leftover
    # budget (ordering, not exclusion), but never ahead of what must be fixed.
    assert query.index("nguồn") < query.index("nháp")
    assert len(query.split()) <= MAX_QUERY_WORDS


def test_the_step_title_still_leads_a_rework_query():
    """Failures outrank the draft, but never the title — it names the subject, and a
    defect list alone ("Thiếu 2 nhược điểm") does not say what the topic is."""
    query = build_search_query(
        "Khảo sát giải pháp zep",
        _rework_brief("nháp cũ", ["Thiếu nhược điểm"]),
    )

    assert query.startswith("Khảo sát giải pháp zep")


def test_the_draft_still_contributes_once_the_defects_are_in():
    """Ordering, not exclusion. The draft is demoted behind the failures, not dropped —
    within the word budget it is still legitimate context for the query."""
    query = build_search_query(
        "Khảo sát Zep",
        _rework_brief("Zep dùng kiến trúc graph memory", ["Thiếu nhược điểm"]),
    )

    assert "nhược điểm" in query
    assert "graph memory" in query
    assert query.index("nhược điểm") < query.index("graph memory")


def test_an_ordinary_brief_is_unaffected_by_the_rework_rule():
    """No failures heading ⇒ byte-identical to the previous behaviour. The rule must
    not perturb the ordinary `work` path, which is every non-rework step."""
    brief = "Chủ đề: thanh toán không tiền mặt\nMốc thời gian: 2026"

    assert build_search_query("Tra cứu xu hướng", brief) == (
        "Tra cứu xu hướng Chủ đề: thanh toán không tiền mặt Mốc thời gian: 2026"
    )


def test_the_placeholder_failure_list_does_not_starve_the_query():
    """A failed verdict with no itemised failures writes "(không có chi tiết)". That
    placeholder must not become the query's leading terms and displace real context."""
    query = build_search_query(
        "Khảo sát Zep",
        _rework_brief("Zep dùng kiến trúc graph memory", []),
    )

    assert "graph memory" in query


def test_blocks_appended_after_the_failure_list_are_not_treated_as_failures():
    """`perceive` appends further blocks after the deps handoff (CEO clarifications,
    coordinator guidance). The failures section is a run of `- ` bullets and must end
    there — otherwise every trailing block inherits top priority in the query merely by
    sitting below the list."""
    handoff = (
        "nháp cũ\n\n"
        "Danh sách lỗi cần sửa:\n"
        "- Thiếu nhược điểm\n\n"
        "CHỈ DẪN CỦA ĐIỀU PHỐI (lần trước chưa đạt):\n"
        "làm lại phần B"
    )

    query = build_search_query("Khảo sát Zep", handoff)

    assert query.index("Thiếu nhược điểm") < query.index("nháp cũ")
    assert query.index("nháp cũ") < query.index("làm lại phần B")
