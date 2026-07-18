"""M3-P12 S2 (B3): mpm agent replay — list/replay checkpoints (injected build_graph)."""

from __future__ import annotations

import sqlite3
from typing import TypedDict

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from my_crew.entrypoints import mpm_replay_cmd
from my_crew.runtime.registry import RegistryEntry

_THREAD = "acme:daily:internal"


class _S(TypedDict):
    x: int


@pytest.fixture
def seeded_build(tmp_path, monkeypatch):
    """A SqliteSaver-backed graph seeded for _THREAD + a fake registry/profile."""

    def perceive(s):
        return {"x": s.get("x", 0) + 1}

    def deliver(s):
        return {"x": s["x"]}  # state-only resume-safe node

    conn = sqlite3.connect(str(tmp_path / "cp.db"), check_same_thread=False)
    b = StateGraph(_S)
    b.add_node("perceive", perceive)
    b.add_node("deliver", deliver)
    b.add_edge(START, "perceive")
    b.add_edge("perceive", "deliver")
    b.add_edge("deliver", END)
    graph = b.compile(checkpointer=SqliteSaver(conn))
    graph.invoke({"x": 0}, {"configurable": {"thread_id": _THREAD}})

    class _Loaded:
        settings = object()  # replay core never reads settings (build_graph is injected)

    monkeypatch.setattr(
        mpm_replay_cmd, "load_registry", lambda: (RegistryEntry("acme", True),)
    )
    monkeypatch.setattr(mpm_replay_cmd, "_load_agent", lambda aid: _Loaded())

    def build_graph(loaded, settings, kind, audience):
        return graph

    yield build_graph
    conn.close()


def test_replay_lists_history(seeded_build, capsys):
    rc = mpm_replay_cmd.run_replay(["acme", _THREAD], build_graph=seeded_build)
    out = capsys.readouterr().out
    assert rc == 0
    assert "checkpoints for" in out
    assert "step=" in out  # at least one checkpoint listed


def test_replay_from_checkpoint(seeded_build, capsys):
    # grab a real checkpoint id from the listing first
    from my_crew.runtime.replay import list_checkpoints

    cps = list_checkpoints(None, None, _THREAD, build_graph=seeded_build)
    cp = cps[0]["checkpoint_id"]
    rc = mpm_replay_cmd.run_replay(
        ["acme", _THREAD, "--checkpoint", cp], build_graph=seeded_build
    )
    assert rc == 0
    assert "replay from" in capsys.readouterr().out


def test_replay_unknown_agent(monkeypatch, capsys):
    monkeypatch.setattr(mpm_replay_cmd, "load_registry", lambda: (RegistryEntry("acme", True),))
    rc = mpm_replay_cmd.run_replay(["ghost", _THREAD])
    assert rc == 1
    assert "unknown agent" in capsys.readouterr().err


def test_replay_bad_invocation(capsys):
    rc = mpm_replay_cmd.run_replay(["acme"])  # missing thread
    assert rc == 2
    assert "usage:" in capsys.readouterr().err


def test_replay_checkpoint_flag_without_value(seeded_build, capsys):
    """`--checkpoint` with no value must error, not silently fall back to listing."""
    rc = mpm_replay_cmd.run_replay(["acme", _THREAD, "--checkpoint"], build_graph=seeded_build)
    assert rc == 2
    assert "--checkpoint requires" in capsys.readouterr().err


def test_replay_unknown_checkpoint_errors(seeded_build, capsys):
    rc = mpm_replay_cmd.run_replay(
        ["acme", _THREAD, "--checkpoint", "nope"], build_graph=seeded_build
    )
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_replay_dispatch_via_mpm(seeded_build, monkeypatch):
    """`mpm agent replay` routes to run_replay."""
    from my_crew.entrypoints import mpm

    called = {}

    def _fake_run_replay(rest, **k):
        called["rest"] = rest
        return 0

    monkeypatch.setattr("my_crew.entrypoints.mpm_replay_cmd.run_replay", _fake_run_replay)
    rc = mpm.main(["agent", "replay", "acme", _THREAD])
    assert rc == 0
    assert called["rest"] == ["acme", _THREAD]
