"""Slice 2: B1 run-event log — append-only JSONL, parseable lines, ts added."""

from __future__ import annotations

import json

from my_crew.runtime.run_event import append_run_event


def test_one_append_one_parseable_line(tmp_path):
    append_run_event(tmp_path, {"agent_id": "default", "kind": "daily", "status": "delivered"})
    lines = (tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["agent_id"] == "default" and event["status"] == "delivered"
    assert "ts" in event  # ts auto-added


def test_two_appends_two_lines_order_preserved(tmp_path):
    append_run_event(tmp_path, {"kind": "daily"})
    append_run_event(tmp_path, {"kind": "weekly"})
    lines = (tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["kind"] for line in lines] == ["daily", "weekly"]


def test_creates_parent_dir(tmp_path):
    nested = tmp_path / "agents" / "x"  # does not exist yet
    append_run_event(nested, {"kind": "daily"})
    assert (nested / "runs.jsonl").exists()
