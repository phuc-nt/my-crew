"""v8 M22: bounded plain-text report summary for the portfolio roll-up. Offline, pure."""

from __future__ import annotations

from my_crew.runtime.report_summary import MAX_SUMMARY_CHARS, summarize_report


def test_empty_is_empty():
    assert summarize_report("") == ""
    assert summarize_report("   \n  ") == ""


def test_short_text_passthrough_stripped():
    assert summarize_report("<p>Đội ổn.</p>") == "Đội ổn."


def test_collapses_whitespace_and_tags():
    out = summarize_report("<h2>Tiêu đề</h2>\n\n<ul><li>A</li>  <li>B</li></ul>")
    assert "<" not in out and ">" not in out
    assert "  " not in out  # whitespace collapsed
    assert "Tiêu đề" in out and "A" in out and "B" in out


def test_bounded_hard_cut_with_ellipsis():
    text = "x" * 1000  # no sentence boundary
    out = summarize_report(text)
    assert len(out) <= MAX_SUMMARY_CHARS + 1  # +1 for the ellipsis
    assert out.endswith("…")


def test_snaps_to_sentence_boundary_near_limit():
    # a sentence ends within the last quarter of the window → cut there, no ellipsis
    body = "Câu một. " * 60  # ~540 chars, sentence ends throughout
    out = summarize_report(body)
    assert out.endswith(".")
    assert len(out) <= MAX_SUMMARY_CHARS


def test_pathological_tag_cannot_blow_the_bound():
    # a giant tag is stripped BEFORE the cut, so the bound holds
    text = "<" + "a" * 5000 + ">nội dung thật"
    out = summarize_report(text)
    assert len(out) <= MAX_SUMMARY_CHARS + 1
    assert "nội dung thật" in out


def test_custom_limit():
    assert len(summarize_report("y" * 100, limit=20)) <= 21
