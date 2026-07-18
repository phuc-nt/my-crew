"""v8 M23 surface 1: the approval-gate auto-approve for scheduled external reports. Offline.

The gate normally interrupts an external report for human approval. With the trust ladder on
and the kind in scheduled_reports, it auto-approves instead → deliver runs WITHOUT a human
resume. Absent/empty config ⇒ interrupt exactly as before (byte-identical). Built as a real
compiled graph (interrupt needs a checkpointer), mirroring test_approval_gate_interrupt.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from langgraph.checkpoint.sqlite import SqliteSaver

from my_crew.agent.report_graph import ReportDeps, build_report_graph
from my_crew.profile.context import ProfileContext
from my_crew.tools.models import CiRun, Issue, PullRequest, Risk


def _checkpointer() -> SqliteSaver:
    saver = SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))
    saver.setup()
    return saver


class _DeliverSpy:
    def __init__(self):
        self.calls = 0

    def __call__(self, short, body, approved=False):
        self.calls += 1
        return True, "slack=executed"


def _fake_deps(deliver) -> ReportDeps:
    return ReportDeps(
        fetch_issues=lambda: [Issue(key="AB-1", summary="x", status="In Progress",
                                    assignee="P", due_date=date(2026, 6, 1), labels=("blocked",))],
        fetch_prs=lambda: [PullRequest(number=9, title="y", author="p",
                                       updated_at=date(2026, 6, 1), review_decision=None,
                                       checks_state="FAILURE", age_days=20, stale=True)],
        fetch_ci=lambda: [CiRun(workflow="ci", status="completed", conclusion="failure")],
        analyze_risks=lambda i, p, c: [Risk(kind="blocker", severity="high", subject="AB-1",
                                            detail="d", suggested_action="a")],
        compose=lambda risks: ("<h2>Báo cáo</h2>", 0.0002, "*short*"),
        deliver=deliver,
    )


def _graph(deliver, checkpointer, *, auto_approve=None, kind="daily"):
    ctx = ProfileContext(auto_approve=auto_approve)
    return build_report_graph(deps=_fake_deps(deliver), audience="external",
                              checkpointer=checkpointer, context=ctx, report_kind=kind)


def _cfg(thread="t"):
    return {"configurable": {"thread_id": thread}}


def test_scheduled_kind_auto_delivers_no_interrupt():
    spy = _DeliverSpy()
    graph = _graph(spy, _checkpointer(), auto_approve={"scheduled_reports": ["daily"]})
    out = graph.invoke({}, _cfg())
    assert "__interrupt__" not in out  # did NOT pause for a human
    assert spy.calls == 1  # delivered
    assert out.get("auto_approved") is True  # flagged for the CEO's "đã tự duyệt" view


def test_kind_not_in_scheduled_still_interrupts():
    spy = _DeliverSpy()
    graph = _graph(spy, _checkpointer(), auto_approve={"scheduled_reports": ["weekly"]})
    out = graph.invoke({}, _cfg())
    assert "__interrupt__" in out  # daily not listed ⇒ pauses
    assert spy.calls == 0


def test_no_config_interrupts_byte_identical():
    spy = _DeliverSpy()
    graph = _graph(spy, _checkpointer(), auto_approve=None)
    out = graph.invoke({}, _cfg())
    assert "__interrupt__" in out and spy.calls == 0
