"""M3-P12 S4: consolidated offline e2e — B4 tracing + B3 replay + D3 automate coexist.

Proves the three P12 features coexist, share the existing infrastructure (the Lớp B
approval queue, the per-thread checkpoint, the invoke config), and that backward-compat
holds (tracing OFF ⇒ byte-identical invoke config). All offline, no network/live keys.
"""

from __future__ import annotations

import sqlite3
from typing import TypedDict

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from src.actions.action_gateway import ActionGateway
from src.audit.audit_log import AuditLog
from src.automation.engine import run_workflow
from src.automation.schema import parse_automation
from src.config.config_builders import build_settings_from_dict
from src.runtime.replay import list_checkpoints, replay_from_checkpoint
from src.runtime.run_config import invoke_config

_THREAD = "acme:daily:internal"
_TRACE_ENV = ("LANGCHAIN_TRACING_V2", "LANGSMITH_API_KEY")


@pytest.fixture
def clean_trace_env(monkeypatch):
    for k in _TRACE_ENV:
        monkeypatch.delenv(k, raising=False)


# --- B4: backward-compat headline — tracing OFF ⇒ byte-identical invoke config ---


def test_b4_tracing_off_byte_identical(clean_trace_env):
    s = build_settings_from_dict({})
    assert invoke_config(_THREAD, s) == {"configurable": {"thread_id": _THREAD}}


def test_b4_tracing_on_adds_callbacks(clean_trace_env, monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    # Stub the tracer so attaching it never opens a real LangSmith connection (no network).
    monkeypatch.setattr(
        "langchain_core.tracers.LangChainTracer", lambda *a, **k: object()
    )
    s = build_settings_from_dict({"tracing": True})
    cfg = invoke_config(_THREAD, s)
    assert "callbacks" in cfg and len(cfg["callbacks"]) == 1


# --- B3: replay a seeded checkpoint (frozen state, no re-fetch) ---


class _S(TypedDict):
    x: int


def test_b3_replay_seeded_checkpoint(tmp_path):
    def perceive(s):
        return {"x": s.get("x", 0) + 5}

    def deliver(s):
        return {"x": s["x"]}

    conn = sqlite3.connect(str(tmp_path / "cp.db"), check_same_thread=False)
    b = StateGraph(_S)
    b.add_node("perceive", perceive)
    b.add_node("deliver", deliver)
    b.add_edge(START, "perceive")
    b.add_edge("perceive", "deliver")
    b.add_edge("deliver", END)
    graph = b.compile(checkpointer=SqliteSaver(conn))
    graph.invoke({"x": 0}, {"configurable": {"thread_id": _THREAD}})

    build = lambda *a: graph  # noqa: E731
    entries = list_checkpoints(None, None, _THREAD, build_graph=build)
    assert entries  # history exists
    replayable = [e for e in entries if e["replayable"]]
    assert replayable
    result = replay_from_checkpoint(
        None, None, _THREAD, replayable[0]["checkpoint_id"], build_graph=build
    )
    assert isinstance(result, dict)
    conn.close()


# --- D3: a propose lands in the SAME Lớp B queue the report path uses ---


def test_d3_propose_into_existing_approval_queue(tmp_path):
    settings = build_settings_from_dict(
        {"dry_run": False, "trust_mode": "guarded", "data_dir": str(tmp_path)}
    )
    gw = ActionGateway(
        settings,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        external_channels=frozenset({"stakeholders"}),
    )
    wf = parse_automation(
        {
            "name": "e2e",
            "steps": [
                {"propose": "slack.post", "args": {"channel": "stakeholders", "text": "hi"}}
            ],
        }
    )
    results = run_workflow(wf, read_tools={}, analyze_fn=lambda p, v: "", gateway=gw)
    assert results[-1].status == "pending_approval"

    # The proposal is in the SAME ApprovalStore the report/cli approve path reads — a fresh
    # gateway over the same data dir sees it (cross-process durability, like a real approve).
    gw2 = ActionGateway(settings, audit_log=AuditLog(tmp_path / "audit.jsonl"))
    pending = gw2.pending_approvals()
    assert len(pending) == 1
    assert pending[0].action["server"] == "slack"


# --- dispatch: replay + automate both resolve through mpm ---


def test_mpm_dispatches_replay_and_automate(monkeypatch):
    from src.entrypoints import mpm

    seen = []
    monkeypatch.setattr(
        "src.entrypoints.mpm_replay_cmd.run_replay", lambda rest, **k: seen.append("replay") or 0
    )
    monkeypatch.setattr(
        "src.entrypoints.mpm_automate_cmd.run_automate",
        lambda rest, **k: seen.append("automate") or 0,
    )
    assert mpm.main(["agent", "replay", "acme", _THREAD]) == 0
    assert mpm.main(["agent", "automate", "acme", "wf.yaml"]) == 0
    assert seen == ["replay", "automate"]
