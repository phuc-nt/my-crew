"""A body cut mid-write is recognised by its shape, not only by finish_reason.

Measured in production (v92): a decomposition came back cut mid-field with no
`finish_reason=length`. The caller read the parse failure as "the model wrote garbage",
so the retry asked for valid JSON — and got the same too-long plan again, one paid round
later. The two retries ask for opposite things, so picking the wrong one is not a
near-miss, it is a wasted attempt.

Hence the design constraint these tests exist to hold: the detector reports ONLY the
unambiguous signature of an interrupted write. Everything else keeps taking the
JSON-error path it took before.
"""

from __future__ import annotations

import pytest

from my_crew.llm.client import LlmResult, looks_truncated


def _result(content: str, finish_reason: str = "") -> LlmResult:
    return LlmResult(
        content=content, model="m", prompt_tokens=1, completion_tokens=1,
        cost_usd=None, finish_reason=finish_reason,
    )


# --- positive: really interrupted -----------------------------------------------------


@pytest.mark.parametrize("body", [
    '{"title": "Kế hoạch", "steps": [{"title": "Bước m',   # cut inside a string
    '{"title": "Kế hoạch", "steps": [',                     # cut after opening an array
    '{"title": "Kế hoạch", "steps": [{"title": "a"}',       # array never closed
    '{"a": 1,',                                             # cut right after a comma
    '[{"step": 1}, {"step": 2}',                            # top-level array left open
])
def test_an_interrupted_body_is_recognised(body):
    assert looks_truncated(body) is True


def test_the_measured_v92_shape_is_caught():
    """The real shape: a plan cut mid-description, several levels deep, no finish_reason."""
    body = (
        '{"title": "Chuẩn bị báo cáo quý", "pic_id": "analyst", "steps": ['
        '{"step_id": "a", "title": "Thu thập số liệu", "assigned_to": "analyst"}, '
        '{"step_id": "b", "title": "Viết phần phân tích chi ti'
    )
    assert looks_truncated(body) is True
    assert _result(body).truncated is True


# --- negative: malformed some OTHER way, must NOT be called truncation ----------------


@pytest.mark.parametrize("body", [
    '{"a": 1,}',              # trailing comma — balanced, just invalid
    '{a: 1}',                 # unquoted key
    '{"a": }',                # missing value
    '{"a": 1} trailing junk',  # complete object plus noise
    '{"a": [1, 2]}',          # perfectly valid
    '',                       # empty
    '   ',                    # blank
])
def test_a_differently_malformed_body_is_not_called_truncated(body):
    """These must keep taking the JSON-error retry: asking for a SHORTER plan would not
    fix any of them."""
    assert looks_truncated(body) is False


def test_prose_is_never_treated_as_a_cut_json_body():
    assert looks_truncated("Xin lỗi, em không thể lập kế hoạch cho việc này.") is False


def test_a_closing_brace_without_an_opener_is_not_truncation():
    """Negative depth is malformed in some other way — the writer did not stop early."""
    assert looks_truncated('{"a": 1}}') is False


# --- the brace/quote bookkeeping ------------------------------------------------------


def test_braces_inside_a_string_do_not_confuse_the_count():
    assert looks_truncated('{"note": "dùng dấu { và } trong mô tả"}') is False


def test_an_escaped_quote_does_not_end_the_string_early():
    assert looks_truncated('{"note": "anh ấy nói \\"xong rồi\\" hôm qua"}') is False


def test_an_escaped_backslash_at_a_string_end_still_closes_it():
    """`"a\\\\"` ends the string; reading the second backslash as an escape would leave it
    open and report a false truncation."""
    assert looks_truncated('{"path": "C:\\\\temp\\\\"}') is False


# --- how LlmResult.truncated uses it --------------------------------------------------


def test_finish_reason_length_still_wins_on_its_own():
    """The explicit provider signal keeps working even when the body looks complete."""
    assert _result('{"a": 1}', finish_reason="length").truncated is True


def test_a_cut_body_is_truncated_even_with_no_finish_reason():
    assert _result('{"a": [1, 2', finish_reason="").truncated is True


def test_an_explicit_stop_is_believed_over_the_shape_guess():
    """The provider saying it finished is stronger evidence than our heuristic. A model
    that deliberately emitted an unbalanced snippet is not a truncation."""
    assert _result('{"a": [1, 2', finish_reason="stop").truncated is False


def test_a_complete_body_that_stopped_normally_is_not_truncated():
    assert _result('{"a": 1}', finish_reason="stop").truncated is False


def test_the_default_construction_still_reports_not_truncated():
    """Every existing test double builds LlmResult without a finish_reason."""
    assert _result("một câu trả lời bình thường").truncated is False
