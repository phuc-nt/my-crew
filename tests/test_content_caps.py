"""v86 Phase 4: content_caps — shared purpose-named caps + continuation footer."""

from __future__ import annotations

from my_crew.runtime.content_caps import (
    ERROR_MSG_CHARS,
    MERGED_ARTIFACT_CHARS,
    PAGE_CONTENT_CHARS,
    TOOL_RESULT_CHARS,
    cap_with_footer,
)


def test_values_pinned_to_the_measured_baseline():
    # Values are the pre-consolidation ones — changing them is BENCH scope (measure
    # first), not hygiene scope. This test makes an accidental drift loud.
    assert PAGE_CONTENT_CHARS == 8000
    assert TOOL_RESULT_CHARS == 6000
    assert ERROR_MSG_CHARS == 300
    assert MERGED_ARTIFACT_CHARS == 256_000


def test_under_cap_passes_through_unchanged():
    assert cap_with_footer("ngắn", 100, "hint") == "ngắn"


def test_exactly_at_cap_passes_through_unchanged():
    text = "x" * 100
    assert cap_with_footer(text, 100, "hint") == text


def test_over_cap_truncates_and_appends_footer():
    text = "a" * 130
    out = cap_with_footer(text, 100, "thu hẹp truy vấn để lấy phần còn lại")
    assert out.startswith("a" * 100)
    assert "a" * 101 not in out
    assert "(Hiển thị 100/130 ký tự. thu hẹp truy vấn để lấy phần còn lại)" in out


def test_footer_sits_on_its_own_line():
    out = cap_with_footer("b" * 20, 10, "hint")
    body, _, footer = out.rpartition("\n")
    assert body == "b" * 10
    assert footer.startswith("(Hiển thị ")
