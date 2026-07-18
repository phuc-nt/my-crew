"""M2-P5 Slice 3: worker fresh-run interrupt detection + --resume path (offline).

The fresh-run interrupt test injects a run_report that returns a paused result
(`__interrupt__`). The resume tests drive `worker_resume.run_resume` directly with a
fake graph builder (no checkpointer, no MCP) so the approve/reject/exit-code contract
is proven without a real process.
"""

from __future__ import annotations

import json

from my_crew.runtime import worker
from my_crew.runtime.worker_resume import run_resume


def _patch_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.agent_paths.DATA_DIR", tmp_path / ".data")
    monkeypatch.setattr("my_crew.runtime.legacy_migration.DATA_DIR", tmp_path / ".data")


# --- fresh run that hits the interrupt: exit 3 + status=interrupted ---


def test_fresh_run_interrupt_exit_3(monkeypatch, tmp_path, capsys):
    _patch_data_dir(monkeypatch, tmp_path)

    def _run(loaded, settings, kind, audience, thread_id):
        return {"__interrupt__": [object()]}  # graph paused at approval_gate

    rc = worker.main(
        ["--agent-id", "default", "--report", "daily", "--audience", "external"],
        run_report=_run,
    )
    assert rc == 3
    runs = tmp_path / ".data" / "agents" / "default" / "runs.jsonl"
    line = json.loads(runs.read_text(encoding="utf-8").strip())
    assert line["status"] == "interrupted"
    assert line["delivered"] is False
    assert "resume with" in capsys.readouterr().out


# --- run_resume: approve delivers (exit 0), reject stops (exit 1) ---


class _FakeGraph:
    """A graph whose invoke records the resume Command + returns a fixed result."""

    def __init__(self, result):
        self._result = result
        self.invoked_with = None

    def invoke(self, command, config):
        self.invoked_with = (command, config)
        return self._result


def _build_graph(result):
    captured = {}

    def _build(loaded, settings, kind, audience):
        captured["kind"] = kind
        captured["audience"] = audience
        graph = _FakeGraph(result)
        captured["graph"] = graph
        return graph

    return _build, captured


def _noop_event(*a, **k):
    return {}


def _events_recorder():
    events = []

    def _append(data_dir, event):
        events.append(event)

    def _make(agent_id, kind, audience, status, cost, delivered):
        return {"status": status, "delivered": delivered, "kind": kind}

    return events, _append, _make


def _flag_value(args, flag):
    if flag in args:
        i = args.index(flag)
        if i + 1 < len(args):
            return args[i + 1]
    return None


def _run(args, *, build_graph, events, append, make):
    return run_resume(
        args, agent_id="default", loaded=object(), settings=object(),
        data_dir="/tmp/x", build_graph=build_graph, flag_value=_flag_value,
        append_event=append, make_event=make,
    )


def test_resume_approve_delivers_exit_0():
    build, captured = _build_graph({"delivered": True, "cost_usd": 0.01})
    events, append, make = _events_recorder()
    rc = _run(
        ["--resume", "--thread", "default:daily:external", "--decision", "approve"],
        build_graph=build, events=events, append=append, make=make,
    )
    assert rc == 0
    assert captured["kind"] == "daily" and captured["audience"] == "external"
    # the resume drove the graph with a Command(resume="approve")
    command, config = captured["graph"].invoked_with
    assert getattr(command, "resume", None) == "approve"
    assert config["configurable"]["thread_id"] == "default:daily:external"
    assert events[-1]["status"] == "delivered"


def test_resume_reject_exit_1_nothing_delivered():
    # reject must NOT invoke the graph's deliver; it records rejected + exits 1.
    build, captured = _build_graph({"delivered": False})
    events, append, make = _events_recorder()
    rc = _run(
        ["--resume", "--thread", "default:okr:external", "--decision", "reject"],
        build_graph=build, events=events, append=append, make=make,
    )
    assert rc == 1
    # reject routes THROUGH the graph (Command(resume="reject") → route_after_gate → END),
    # so the rejection is audited in-graph and deliver never runs.
    command, _ = captured["graph"].invoked_with
    assert getattr(command, "resume", None) == "reject"
    assert events[-1]["status"] == "rejected"
    assert events[-1]["delivered"] is False


def test_resume_bad_decision_exit_2():
    build, _ = _build_graph({"delivered": True})
    events, append, make = _events_recorder()
    rc = _run(
        ["--resume", "--thread", "default:daily:external", "--decision", "maybe"],
        build_graph=build, events=events, append=append, make=make,
    )
    assert rc == 2


def test_resume_thread_not_this_agent_exit_2():
    build, _ = _build_graph({"delivered": True})
    events, append, make = _events_recorder()
    rc = _run(
        ["--resume", "--thread", "other:daily:external", "--decision", "approve"],
        build_graph=build, events=events, append=append, make=make,
    )
    assert rc == 2  # refuse to resume another agent's thread


def test_resume_malformed_thread_exit_2():
    build, _ = _build_graph({"delivered": True})
    events, append, make = _events_recorder()
    rc = _run(
        ["--resume", "--thread", "not-a-thread", "--decision", "approve"],
        build_graph=build, events=events, append=append, make=make,
    )
    assert rc == 2
