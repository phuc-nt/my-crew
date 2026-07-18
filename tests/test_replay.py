"""M3-P12 S2 (B3): run replay core — frozen-state replay, no live re-fetch.

Offline: a tiny graph backed by a tmp SqliteSaver, seeded once. Proves replay resumes
from the stored checkpoint state WITHOUT re-running the perceive/fetch node (the H×H
re-fetch risk), lists checkpoint history with non-PII summaries, and errors cleanly on
an unknown checkpoint.
"""

from __future__ import annotations

import sqlite3
from typing import TypedDict

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from my_crew.runtime.replay import list_checkpoints, replay_from_checkpoint

_THREAD = "acme:daily:internal"  # parse_thread_id-compatible


class _S(TypedDict):
    x: int
    report_text: str


@pytest.fixture
def seeded(tmp_path):
    """A graph with a SqliteSaver + one seeded run for _THREAD. Tracks perceive calls."""
    calls = {"perceive": 0, "deliver": 0}

    def perceive(s):
        calls["perceive"] += 1
        # Writes report_text into STATE (checkpointed) — mirrors the real graphs' deliver
        # being state-only; perceive is the fetch node a replay must not re-run.
        return {"report_text": "SECRET per-assignee detail", "x": s.get("x", 0) + 10}

    def deliver(s):
        calls["deliver"] += 1
        return {"x": s["x"]}  # reads ONLY checkpointed state (resume-safe node)

    conn = sqlite3.connect(str(tmp_path / "cp.db"), check_same_thread=False)
    saver = SqliteSaver(conn)
    b = StateGraph(_S)
    b.add_node("perceive", perceive)
    b.add_node("deliver", deliver)
    b.add_edge(START, "perceive")
    b.add_edge("perceive", "deliver")
    b.add_edge("deliver", END)
    graph = b.compile(checkpointer=saver)
    graph.invoke({"x": 0, "report_text": ""}, {"configurable": {"thread_id": _THREAD}})

    def build_graph(loaded, settings, kind, audience):
        return graph

    yield build_graph, calls
    conn.close()


def test_list_checkpoints_returns_entries_no_pii(seeded):
    build_graph, _ = seeded
    entries = list_checkpoints(None, None, _THREAD, build_graph=build_graph)
    assert entries and entries[0]["checkpoint_id"]
    # summary is structural only — no report text / PII leaks into the listing
    blob = str(entries)
    assert "SECRET" not in blob and "report_text" not in blob
    assert set(entries[0]) == {
        "checkpoint_id", "step", "source", "next", "created_at", "replayable"
    }


def test_replay_from_deliver_checkpoint_does_not_refetch(seeded):
    """Replay from a post-perceive checkpoint (pending deliver) does NOT re-run perceive."""
    build_graph, calls = seeded
    entries = list_checkpoints(None, None, _THREAD, build_graph=build_graph)
    pending_deliver = [e for e in entries if e["next"] == ["deliver"]]
    assert pending_deliver, "expected a checkpoint pending the deliver node"
    assert pending_deliver[0]["replayable"] is True
    cp = pending_deliver[0]["checkpoint_id"]

    before = calls["perceive"]
    result = replay_from_checkpoint(None, None, _THREAD, cp, build_graph=build_graph)
    assert result["x"] == 10
    assert calls["perceive"] == before  # NO re-fetch — frozen-state replay


def test_replay_refuses_pre_fetch_checkpoint(seeded):
    """A checkpoint pending perceive (the fetch node) is refused — would re-fetch live data."""
    build_graph, _ = seeded
    entries = list_checkpoints(None, None, _THREAD, build_graph=build_graph)
    pending_perceive = [e for e in entries if e["next"] == ["perceive"]]
    assert pending_perceive, "expected a pre-perceive checkpoint"
    assert pending_perceive[0]["replayable"] is False
    cp = pending_perceive[0]["checkpoint_id"]
    with pytest.raises(ValueError, match="pending"):
        replay_from_checkpoint(None, None, _THREAD, cp, build_graph=build_graph)


def test_replay_unknown_checkpoint_errors(seeded):
    build_graph, _ = seeded
    with pytest.raises(ValueError, match="not found"):
        replay_from_checkpoint(None, None, _THREAD, "nope", build_graph=build_graph)


def test_replay_requires_checkpoint_id(seeded):
    build_graph, _ = seeded
    with pytest.raises(ValueError, match="requires a checkpoint_id"):
        replay_from_checkpoint(None, None, _THREAD, "", build_graph=build_graph)


def test_list_checkpoints_empty_thread(seeded):
    build_graph, _ = seeded
    assert list_checkpoints(None, None, "acme:weekly:internal", build_graph=build_graph) == []
