"""M2-P5 Slice 2: graph-native Lớp B interrupt in the OKR + resource graphs.

Same pause→resume contract as the daily/weekly report graph (Slice 1), extended to
the other two external-capable graphs. Offline — fake deps + in-memory SqliteSaver.
"""

from __future__ import annotations

import sqlite3

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from src.agent.okr_analyzer import OkrRollup
from src.agent.okr_report_graph import OkrReportDeps, build_okr_graph
from src.agent.resource_report_graph import ResourceReportDeps, build_resource_graph
from src.tools.models import (
    AssigneeLoad,
    CostSummary,
    KeyResult,
    Objective,
    OkrProblem,
    ResourceReport,
)


def _checkpointer() -> SqliteSaver:
    saver = SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))
    saver.setup()
    return saver


def _cfg(thread="t"):
    return {"configurable": {"thread_id": thread}}


class _Spy:
    """Records deliver calls + the approved flag (proves single live delivery)."""

    def __init__(self) -> None:
        self.calls = 0
        self.approved_seen: list[bool] = []

    def _record(self, approved):
        self.calls += 1
        self.approved_seen.append(approved)
        return True, "confluence=executed slack=executed url=https://x"


def _rollup() -> OkrRollup:
    obj = Objective(
        name="O1",
        key_results=(KeyResult("KR1", ("ABC-1",), 1.0, progress_pct=80.0),),
        progress_pct=80.0,
    )
    return OkrRollup(objectives=(obj,), problems=(OkrProblem("O1", "x"),), at_risk=())


def _resource() -> ResourceReport:
    loads = (AssigneeLoad("Carol", 6, 2, 1, overloaded=True),)
    return ResourceReport(loads=loads, team_mean=4.0, overloaded=("Carol",), unassigned_count=1)


def _cost() -> CostSummary:
    return CostSummary(
        llm_spent=45.0, llm_cap=50.0, llm_ratio=0.9, llm_status="warn",
        labor_estimate=200.0, open_issue_count=8, cost_per_issue=25.0,
    )


def _okr_graph(spy, *, audience, checkpointer):
    deps = OkrReportDeps(
        fetch_rollup=lambda: _rollup(),
        compose=lambda r: ("<p>okr</p>", None),
        deliver=lambda r, body, approved=False: spy._record(approved),
    )
    return build_okr_graph(deps=deps, audience=audience, checkpointer=checkpointer)


def _resource_graph(spy, *, audience, checkpointer):
    deps = ResourceReportDeps(
        fetch=lambda: (_resource(), _cost()),
        compose=lambda r, c: ("<p>rc</p>", None),
        deliver=lambda r, c, body, approved=False: spy._record(approved),
    )
    return build_resource_graph(deps=deps, audience=audience, checkpointer=checkpointer)


# graph-builder factories parametrized so both graphs run the identical contract
GRAPHS = [("okr", _okr_graph), ("resource", _resource_graph)]


@pytest.mark.parametrize("name,make", GRAPHS)
def test_external_pauses_at_gate(name, make):
    spy = _Spy()
    graph = make(spy, audience="external", checkpointer=_checkpointer())
    out = graph.invoke({}, _cfg())
    assert "__interrupt__" in out
    assert spy.calls == 0
    assert graph.get_state(_cfg()).next == ("approval_gate",)


@pytest.mark.parametrize("name,make", GRAPHS)
def test_resume_approve_delivers_live(name, make):
    spy = _Spy()
    cp = _checkpointer()
    graph = make(spy, audience="external", checkpointer=cp)
    graph.invoke({}, _cfg())
    out = graph.invoke(Command(resume="approve"), _cfg())
    assert out["delivered"] is True
    assert spy.calls == 1
    assert spy.approved_seen == [True]  # already-approved path
    assert graph.get_state(_cfg()).next == ()


@pytest.mark.parametrize("name,make", GRAPHS)
def test_resume_reject_stops_clean(name, make):
    spy = _Spy()
    cp = _checkpointer()
    graph = make(spy, audience="external", checkpointer=cp)
    graph.invoke({}, _cfg())
    out = graph.invoke(Command(resume="reject"), _cfg())
    assert spy.calls == 0
    assert not out.get("delivered")
    assert graph.get_state(_cfg()).next == ()


@pytest.mark.parametrize("name,make", GRAPHS)
def test_internal_no_pause(name, make):
    spy = _Spy()
    graph = make(spy, audience="internal", checkpointer=None)
    out = graph.invoke({}, _cfg())
    assert "__interrupt__" not in out
    assert out["delivered"] is True
    assert spy.approved_seen == [False]  # internal path never approved
