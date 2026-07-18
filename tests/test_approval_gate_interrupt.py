"""M2-P5 Slice 1: graph-native Lớp B interrupt in the report graph.

Offline — fake deps (no network/LLM/MCP) + an in-memory SqliteSaver checkpointer
(interrupt() requires a checkpointer). Proves: external audience PAUSES at
`approval_gate` before any delivery, resume-approve delivers exactly once,
resume-reject stops clean, internal audience is an unchanged pass-through, and the
interrupt payload leaks no profile data.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from my_crew.agent.report_graph import ReportDeps, build_report_graph
from my_crew.profile.context import ProfileContext
from my_crew.tools.models import CiRun, Issue, PullRequest, Risk


def _checkpointer() -> SqliteSaver:
    saver = SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))
    saver.setup()
    return saver


class _DeliverSpy:
    """Records deliver calls so a paused graph can be proven to NOT deliver.

    Also records the `approved` flag the node passes, to prove approve-resume runs
    the already-approved path and reject (if it ever ran) would not.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.approved_seen: list[bool] = []

    def __call__(self, short, body, approved=False):
        self.calls += 1
        self.approved_seen.append(approved)
        return True, "confluence=executed slack=executed url=https://x"


def _fake_deps(deliver) -> ReportDeps:
    return ReportDeps(
        fetch_issues=lambda: [
            Issue(key="AB-1", summary="x", status="In Progress", assignee="P",
                  due_date=date(2026, 6, 1), labels=("blocked",))
        ],
        fetch_prs=lambda: [
            PullRequest(number=9, title="y", author="p", updated_at=date(2026, 6, 1),
                        review_decision=None, checks_state="FAILURE", age_days=20, stale=True)
        ],
        fetch_ci=lambda: [CiRun(workflow="ci", status="completed", conclusion="failure")],
        analyze_risks=lambda i, p, c: [
            Risk(kind="blocker", severity="high", subject="AB-1", detail="d", suggested_action="a")
        ],
        compose=lambda risks: ("<h2>Báo cáo</h2>", 0.0002, "*short*"),
        deliver=deliver,
    )


def _external_graph(deliver, checkpointer):
    return build_report_graph(deps=_fake_deps(deliver), audience="external",
                              checkpointer=checkpointer)


def _cfg(thread="t"):
    return {"configurable": {"thread_id": thread}}


def test_external_pauses_at_gate():
    spy = _DeliverSpy()
    graph = _external_graph(spy, _checkpointer())
    out = graph.invoke({}, _cfg())
    assert "__interrupt__" in out  # paused, not finished
    assert spy.calls == 0  # deliver never ran
    assert "delivered" not in out
    assert graph.get_state(_cfg()).next == ("approval_gate",)


def test_resume_approve_delivers():
    spy = _DeliverSpy()
    cp = _checkpointer()
    graph = _external_graph(spy, cp)
    graph.invoke({}, _cfg())  # pause
    out = graph.invoke(Command(resume="approve"), _cfg())
    assert out["delivered"] is True
    assert spy.calls == 1
    assert spy.approved_seen == [True]  # node passed the already-approved flag
    assert graph.get_state(_cfg()).next == ()  # finished


def test_resume_reject_stops_clean():
    spy = _DeliverSpy()
    cp = _checkpointer()
    graph = _external_graph(spy, cp)
    graph.invoke({}, _cfg())  # pause
    out = graph.invoke(Command(resume="reject"), _cfg())
    assert spy.calls == 0  # nothing delivered
    assert not out.get("delivered")
    assert graph.get_state(_cfg()).next == ()  # stopped clean at END


def test_internal_no_pause():
    spy = _DeliverSpy()
    # internal = pass-through; no checkpointer needed (interrupt never called)
    graph = build_report_graph(deps=_fake_deps(spy), audience="internal")
    out = graph.invoke({}, _cfg())
    assert "__interrupt__" not in out
    assert out["delivered"] is True
    assert spy.calls == 1


def test_interrupt_payload_has_no_profile():
    # Even with a hostile profile context, the interrupt payload is channel/kind only.
    secret = "SUPER_SECRET_PERSONA_AND_PROJECT_AND_MEMORY"
    ctx = ProfileContext(persona=secret, project=secret, memory=secret)
    spy = _DeliverSpy()
    graph = build_report_graph(deps=_fake_deps(spy), audience="external",
                               context=ctx, checkpointer=_checkpointer())
    out = graph.invoke({}, _cfg())
    payload = out["__interrupt__"][0].value
    assert secret not in str(payload)


def test_external_summary_channel_branch_has_no_profile():
    # The channel-BEARING branch (real config, audience=external) — the summary must
    # contain only the report kind + stakeholder channel, never profile data.
    from my_crew.agent.approval_gate import external_summary
    from my_crew.config.config_builders import build_reporting_config_from_dict

    cfg = build_reporting_config_from_dict(
        {"slack_stakeholder_channel": "C_EXT", "slack_external_channels": "C_EXT"}
    )
    summary = external_summary("weekly", "external", cfg)()
    assert "C_EXT" in summary  # channel present
    assert "weekly" in summary
    # nothing profile-shaped leaks (the function never receives a ProfileContext)
    for marker in ("persona", "project", "memory", "SOUL"):
        assert marker.lower() not in summary.lower()
