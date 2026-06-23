"""Slice A: OKR read — Confluence table parser + Python epic-progress (pure, no MCP)."""

from __future__ import annotations

import pytest

from src.tools import okr_read
from src.tools.confluence_read import (
    _blocks_text_list,
    _extract_body,
    parse_epic_keys,
    parse_okr_table,
    parse_weight,
)
from src.tools.models import EpicProgress, Issue

# The verified round-trip XHTML body (createPage → getPageContent, 2026-06-22):
# a header row + two data rows, the second with an empty Objective cell (a
# continuation row of a multi-KR objective).
_OKR_BODY = (
    "<p>OKR Q3</p>"
    "<table><tbody>"
    "<tr><th>Objective</th><th>Key Result</th><th>Epic Key(s)</th><th>Weight</th></tr>"
    "<tr><td>Tăng retention</td><td>KR1 churn &lt; 5%</td><td>ABC-1, ABC-2</td><td>0.7</td></tr>"
    "<tr><td></td><td>KR2 NPS &gt; 40</td><td>ABC-3</td><td>0.3</td></tr>"
    "</tbody></table>"
)


def _issue(key: str, status: str) -> Issue:
    return Issue(key=key, summary="", status=status, assignee=None, due_date=None)


# --- Confluence body extraction ---


def test_extract_body_after_content_marker():
    blocks = ["📄 Page", "📝 Content:", "<p>hi</p><table></table>"]
    assert _extract_body(blocks) == "<p>hi</p><table></table>"


def test_extract_body_falls_back_to_markup_block():
    blocks = ["just text", "<table><tr><td>x</td></tr></table>"]
    assert "<table>" in _extract_body(blocks)


def test_blocks_text_list_handles_dicts_and_strings():
    assert _blocks_text_list([{"text": "a"}, "b"]) == ["a", "b"]
    assert _blocks_text_list("solo") == ["solo"]


# --- OKR table parsing ---


def test_parse_okr_table_well_formed():
    quads, problems = parse_okr_table(_OKR_BODY)
    assert problems == []
    assert len(quads) == 2
    # Header dropped; objective carried forward to the continuation row.
    assert quads[0] == ("Tăng retention", "KR1 churn < 5%", "ABC-1, ABC-2", "0.7")
    assert quads[1][0] == "Tăng retention"  # carried forward
    assert quads[1][1] == "KR2 NPS > 40"


def test_parse_okr_table_short_row_is_a_problem():
    body = (
        "<table><tbody>"
        "<tr><th>Objective</th><th>Key Result</th><th>Epic Key(s)</th><th>Weight</th></tr>"
        "<tr><td>O1</td><td>KR1</td><td>ABC-1</td><td>1</td></tr>"
        "<tr><td>broken</td><td>only two</td></tr>"
        "</tbody></table>"
    )
    quads, problems = parse_okr_table(body)
    assert len(quads) == 1  # the good row still parses
    assert len(problems) == 1
    assert "thiếu cột" in problems[0].reason


def test_parse_okr_table_first_row_missing_objective_is_a_problem():
    body = (
        "<table><tbody>"
        "<tr><td></td><td>KR-orphan</td><td>ABC-1</td><td></td></tr>"
        "</tbody></table>"
    )
    quads, problems = parse_okr_table(body)
    assert quads == []
    assert len(problems) == 1
    assert "Objective" in problems[0].reason


def test_parse_okr_table_empty_content():
    quads, problems = parse_okr_table("")
    assert quads == [] and problems == []


def test_parse_okr_table_nested_table_does_not_drop_row():
    # A nested <table> inside a cell must not split or drop the real OKR row.
    body = (
        "<table><tbody>"
        "<tr><th>Objective</th><th>Key Result</th><th>Epic Key(s)</th><th>Weight</th></tr>"
        "<tr><td>O1</td>"
        "<td>KR1 <table><tbody><tr><td>nested</td></tr></tbody></table> note</td>"
        "<td>ABC-1</td><td>1</td></tr>"
        "</tbody></table>"
    )
    quads, problems = parse_okr_table(body)
    assert len(quads) == 1  # the real row survives despite the nested table
    assert quads[0][0] == "O1"
    assert quads[0][2] == "ABC-1"
    assert problems == []


# --- cell parsers ---


def test_parse_epic_keys_split_upper_dedupe_order():
    assert parse_epic_keys("abc-1, abc-2  abc-1") == ("ABC-1", "ABC-2")
    assert parse_epic_keys("") == ()
    assert parse_epic_keys("  ") == ()


def test_parse_epic_keys_rejects_jql_injection():
    # User-typed cells must not interpolate arbitrary text into JQL. Only tokens of
    # the exact PROJECT-123 shape survive; injection fragments (with parens, spaces,
    # operators) are dropped, so they can never reach the JQL string.
    cell = "PROJ-1) OR (created >= -30d) OR (key = ADMIN-1"
    # PROJ-1) has a trailing paren → rejected; the bare ADMIN-1 is itself a valid
    # key shape and survives, but the dangerous operators/parens are gone.
    assert parse_epic_keys(cell) == ("ADMIN-1",)
    assert parse_epic_keys("not-a-key DROP TABLE; --") == ()
    assert parse_epic_keys("MPM-12 garbage MPM-13") == ("MPM-12", "MPM-13")
    assert parse_epic_keys("PROJ-1)") == ()  # trailing paren rejected


def test_parse_weight():
    assert parse_weight("") is None
    assert parse_weight("0.4") == pytest.approx(0.4)
    assert parse_weight("40%") == pytest.approx(0.4)
    with pytest.raises(ValueError):
        parse_weight("abc")


# --- epic progress (pure compute) ---


def test_compute_epic_progress_partial():
    children = [_issue("A-1", "Done"), _issue("A-2", "To Do"),
                _issue("A-3", "In Progress"), _issue("A-4", "Closed")]
    ep = okr_read.compute_epic_progress(children, epic_key="E-1")
    assert ep.done_count == 2 and ep.total_count == 4
    assert ep.progress_pct == pytest.approx(50.0)
    assert ep.found is True


def test_compute_epic_progress_no_children_is_not_found():
    ep = okr_read.compute_epic_progress([], epic_key="E-9")
    assert ep.found is False
    assert ep.progress_pct is None and ep.total_count == 0


# --- epic progress fetch (monkeypatched call_tool) ---


class _CFG:
    """Minimal ReportingConfig stub: get_epic_progress only reads jira_server,
    and call_tool is monkeypatched, so a None server is fine."""

    jira_server = None


def test_get_epic_progress_uses_parent_jql_first(monkeypatch):
    calls: list[str] = []

    def fake_call_tool(spec, tool, args):
        calls.append(args["jql"])
        return {"issues": [{"key": "C-1", "status": {"name": "Done"}},
                           {"key": "C-2", "status": {"name": "To Do"}}]}

    monkeypatch.setattr(okr_read, "call_tool", fake_call_tool)
    ep = okr_read.get_epic_progress("EP-1", config=_CFG)
    assert ep.found and ep.done_count == 1 and ep.total_count == 2
    assert calls == ["parent = EP-1"]  # second JQL not needed


def test_get_epic_progress_falls_back_to_epic_link(monkeypatch):
    calls: list[str] = []

    def fake_call_tool(spec, tool, args):
        calls.append(args["jql"])
        if args["jql"].startswith("parent"):
            return {"issues": []}
        return {"issues": [{"key": "C-1", "status": {"name": "Done"}}]}

    monkeypatch.setattr(okr_read, "call_tool", fake_call_tool)
    ep = okr_read.get_epic_progress("EP-2", config=_CFG)
    assert ep.found and ep.total_count == 1
    assert calls == ["parent = EP-2", '"Epic Link" = EP-2']


def test_get_epic_progress_not_found_when_no_children(monkeypatch):
    monkeypatch.setattr(okr_read, "call_tool", lambda spec, tool, args: {"issues": []})
    ep = okr_read.get_epic_progress("EP-3", config=_CFG)
    assert ep.found is False


def test_get_epic_progress_map_memoizes(monkeypatch):
    counter: dict[str, int] = {}

    def fake_get(key, *, config=None, server=None):
        counter[key] = counter.get(key, 0) + 1
        return EpicProgress(key, 50.0, 1, 2, True)

    monkeypatch.setattr(okr_read, "get_epic_progress", fake_get)
    out = okr_read.get_epic_progress_map(["E-1", "E-2", "E-1"], config=_CFG)
    assert set(out) == {"E-1", "E-2"}
    assert counter["E-1"] == 1  # fetched once despite appearing twice
