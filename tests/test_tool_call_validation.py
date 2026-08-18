"""Salvage → repair → coerce pipeline for model-emitted tool arguments (Pi convention).

The pipeline NEVER raises: malformed input degrades to an error the model can act on,
because in a tool loop an exception kills the whole step while an instructive tool
result costs one round.
"""

from __future__ import annotations

from my_crew.runtime_backends.tool_call_validation import (
    coerce_arguments,
    prepare_tool_arguments,
    salvage_arguments,
)
from my_crew.runtime_backends.typed_tool_specs import ToolSpec


def _spec(**over) -> ToolSpec:
    base = dict(
        name="history_search",
        legacy_name="history.search",
        description="d",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "days": {"type": "integer"},
                "agent": {"type": "string"},
            },
            "required": ["query"],
        },
    )
    base.update(over)
    return ToolSpec(**base)


# --- salvage: model-emitted JSON string → dict, never raises ---

def test_salvage_valid_json():
    assert salvage_arguments('{"query": "a"}') == {"query": "a"}


def test_salvage_empty_and_none():
    assert salvage_arguments("") == {}
    assert salvage_arguments(None) == {}


def test_salvage_trailing_comma():
    assert salvage_arguments('{"query": "a",}') == {"query": "a"}


def test_salvage_single_quotes():
    assert salvage_arguments("{'query': 'a'}") == {"query": "a"}


def test_salvage_non_object_payloads_degrade_to_empty():
    assert salvage_arguments('"just a string"') == {}
    assert salvage_arguments("[1,2]") == {}
    assert salvage_arguments("total garbage {{{") == {}


# --- coerce: schema-aware cleanup, returns (args, dropped_names) ---

def test_coerce_passthrough():
    args, dropped = coerce_arguments({"query": "a", "days": 3}, _spec().parameters)
    assert args == {"query": "a", "days": 3}
    assert dropped == []


def test_coerce_drops_null_optionals_keeps_required_null_visible():
    args, dropped = coerce_arguments({"query": "a", "days": None}, _spec().parameters)
    assert args == {"query": "a"}
    assert dropped == []


def test_coerce_string_to_int():
    args, _ = coerce_arguments({"query": "a", "days": "7"}, _spec().parameters)
    assert args["days"] == 7


def test_coerce_number_to_string():
    args, _ = coerce_arguments({"query": 42}, _spec().parameters)
    assert args["query"] == "42"


def test_coerce_drops_invented_fields_and_reports_them():
    args, dropped = coerce_arguments(
        {"query": "a", "recursive": True, "max_results": 5}, _spec().parameters
    )
    assert args == {"query": "a"}
    assert sorted(dropped) == ["max_results", "recursive"]


def test_coerce_uncoercible_value_left_as_is():
    # "many" cannot become an integer — leave it; the tool's own guard message beats
    # a validation crash, and the callable already degrades errors to strings
    args, _ = coerce_arguments({"query": "a", "days": "many"}, _spec().parameters)
    assert args["days"] == "many"


# --- prepare: full pipeline (salvage → per-tool repair hook → coerce → required check) ---

def test_prepare_happy_path():
    args, error, notes = prepare_tool_arguments(_spec(), '{"query": "giá spotify"}')
    assert args == {"query": "giá spotify"}
    assert error is None
    assert notes == []


def test_prepare_missing_required_returns_actionable_error():
    args, error, notes = prepare_tool_arguments(_spec(), "{}")
    assert args is None
    assert "query" in error
    assert "history_search" in error


def test_prepare_runs_repair_hook_before_validation():
    spec = ToolSpec(
        name="web_fetch",
        legacy_name="web.scrape",
        description="d",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        prepare_arguments=lambda a: {"url": a.get("url") or a.get("query") or ""},
    )
    args, error, _ = prepare_tool_arguments(spec, '{"query": "https://x.example"}')
    assert error is None
    assert args == {"url": "https://x.example"}


def test_prepare_reports_dropped_fields_in_notes():
    _, error, notes = prepare_tool_arguments(_spec(), '{"query": "a", "limit": 3}')
    assert error is None
    assert notes and "limit" in notes[0]


def test_prepare_repair_hook_crash_degrades_to_error_not_raise():
    def _boom(args: dict) -> dict:
        raise ValueError("hook bug")

    spec = _spec(prepare_arguments=_boom)
    args, error, _ = prepare_tool_arguments(spec, '{"query": "a"}')
    assert args is None
    assert "history_search" in error
