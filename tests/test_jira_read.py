"""Jira read: raw JSON → Issue normalization (pure parse, no MCP)."""

from __future__ import annotations

from datetime import date

import pytest

from my_crew.tools.jira_read import is_done, parse_issue


def test_parse_full_issue():
    raw = {
        "key": "AB-1",
        "fields": {
            "summary": "Fix login",
            "status": {"name": "In Progress"},
            "assignee": {"displayName": "Phuc"},
            "duedate": "2026-06-15",
            "labels": ["backend", "blocked"],
        },
    }
    issue = parse_issue(raw)
    assert issue.key == "AB-1"
    assert issue.status == "In Progress"
    assert issue.assignee == "Phuc"
    assert issue.due_date == date(2026, 6, 15)
    assert issue.labels == ("backend", "blocked")


def test_parse_missing_optionals():
    issue = parse_issue({"key": "AB-2", "fields": {}})
    assert issue.status == "Unknown"
    assert issue.assignee is None
    assert issue.due_date is None


def test_parse_no_key_raises():
    with pytest.raises(ValueError, match="missing 'key'"):
        parse_issue({"fields": {}})


def test_bad_duedate_is_none():
    issue = parse_issue({"key": "AB-3", "fields": {"duedate": "not-a-date"}})
    assert issue.due_date is None


def test_is_done():
    done = parse_issue({"key": "X", "fields": {"status": {"name": "Done"}}})
    closed = parse_issue({"key": "Y", "fields": {"status": {"name": "Closed"}}})
    open_ = parse_issue({"key": "Z", "fields": {"status": {"name": "To Do"}}})
    assert is_done(done) and is_done(closed)
    assert not is_done(open_)


def test_flagged_via_label():
    issue = parse_issue({"key": "F-1", "fields": {"labels": ["Flagged"]}})
    assert issue.flagged is True


# --- Flat shape: what the Jira MCP server actually returns (verified 2026-06-21) ---
# status/assignee/summary/labels live at top level, NOT under `fields`.


def test_parse_flat_shape_from_mcp_server():
    raw = {
        "key": "SCRUM-3",
        "summary": "Subtask 2.1",
        "status": {"name": "In Progress", "category": "In Progress"},
        "assignee": None,
        "labels": [],
    }
    issue = parse_issue(raw)
    assert issue.key == "SCRUM-3"
    assert issue.status == "In Progress"  # read from top-level, not fields.*
    assert issue.assignee is None
    assert issue.labels == ()


def test_parse_flat_assignee_object():
    raw = {"key": "X-1", "assignee": {"displayName": "Phuc"}, "status": "To Do"}
    issue = parse_issue(raw)
    assert issue.assignee == "Phuc"
    assert issue.status == "To Do"  # status as a plain string


def test_parse_flat_assignee_string():
    issue = parse_issue({"key": "X-2", "assignee": "phuc", "status": {"name": "Done"}})
    assert issue.assignee == "phuc"
