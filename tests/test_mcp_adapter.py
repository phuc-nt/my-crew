"""MCP adapter: result coercion + tool-by-name lookup (no real subprocess)."""

from __future__ import annotations

from my_crew.adapters.mcp_adapter import _coerce_result


def test_coerce_json_string():
    assert _coerce_result('{"a": 1}') == {"a": 1}


def test_coerce_plain_string_passthrough():
    assert _coerce_result("hello") == "hello"


def test_coerce_message_content():
    class Msg:
        content = '{"x": 2}'

    assert _coerce_result(Msg()) == {"x": 2}


def test_coerce_message_plain_content():
    class Msg:
        content = "plain"

    assert _coerce_result(Msg()) == "plain"


def test_coerce_already_dict():
    assert _coerce_result({"k": "v"}) == {"k": "v"}


# --- MCP content-block shape: what real servers return (verified 2026-06-21) ---


def test_coerce_content_block_single_json():
    # [{"type": "text", "text": "<json>"}] -> parsed object
    raw = [{"type": "text", "text": '{"issues": [{"key": "AB-1"}]}'}]
    assert _coerce_result(raw) == {"issues": [{"key": "AB-1"}]}


def test_coerce_content_block_single_plain_text():
    raw = [{"type": "text", "text": "just text"}]
    assert _coerce_result(raw) == "just text"


def test_coerce_content_block_multiple():
    raw = [{"type": "text", "text": '{"a": 1}'}, {"type": "text", "text": '{"b": 2}'}]
    assert _coerce_result(raw) == [{"a": 1}, {"b": 2}]


def test_coerce_toolmessage_with_content_block():
    class Msg:
        content = [{"type": "text", "text": '{"ok": true}'}]

    assert _coerce_result(Msg()) == {"ok": True}
