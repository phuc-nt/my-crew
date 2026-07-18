"""M2-P6 Slice 4: resume-safe deliver — REBUILD the graph between pause and resume.

The real worker REBUILDS the graph on resume (fresh empty closure `box`), unlike the
existing interrupt tests which reuse the same graph object (so the box survives). This
reproduces the real path: build → pause at the gate → build a FRESH graph sharing the
SAME SqliteSaver + thread → resume → assert deliver posts the CORRECT short, proving it
came from checkpointed state, not the (now-empty) box. Today (pre-fix) okr/resource
would KeyError and daily would post a degraded empty-risk short.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from my_crew.agent.okr_analyzer import OkrRollup
from my_crew.agent.okr_report_graph import OkrReportDeps, build_okr_graph
from my_crew.agent.report_graph import ReportDeps, build_report_graph
from my_crew.agent.resource_report_graph import ResourceReportDeps, build_resource_graph
from my_crew.llm.okr_report_prompt import build_okr_slack_short
from my_crew.llm.report_slack_short import build_slack_short
from my_crew.llm.resource_report_prompt import build_resource_slack_short
from my_crew.tools.models import (
    AssigneeLoad,
    CiRun,
    CostSummary,
    Issue,
    KeyResult,
    Objective,
    OkrProblem,
    ResourceReport,
    Risk,
)


def _cp() -> SqliteSaver:
    saver = SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))
    saver.setup()
    return saver


def _cfg(thread):
    return {"configurable": {"thread_id": thread}}


class _ShortSpy:
    """Records the URL-free short the deliver node carried out of state."""

    def __init__(self) -> None:
        self.calls = 0
        self.posted_short: str | None = None

    def __call__(self, short, body, approved=False, attachment_path=None):
        self.calls += 1
        self.posted_short = short
        return True, "confluence=executed slack=executed url=https://x"


# --- daily/weekly: resume must post the REAL-risk short, not the degraded empty one ---


def _daily_deps(spy):
    risks = [Risk(kind="blocker", severity="high", subject="AB-1", detail="d",
                  suggested_action="a")]
    return ReportDeps(
        fetch_issues=lambda: [Issue(key="AB-1", summary="x", status="To Do", assignee="P",
                                    due_date=date(2026, 6, 1), labels=())],
        fetch_prs=lambda: [],
        fetch_ci=lambda: [CiRun(workflow="ci", status="completed", conclusion="failure")],
        analyze_risks=lambda i, p, c: risks,
        # the REAL short built from the REAL risks, URL-free (what compose checkpoints)
        compose=lambda rs: ("<h2>body</h2>", 0.0,
                            build_slack_short(rs, report_date="2026-06-25", detail_url=None,
                                              audience="external")),
        deliver=spy,
    )


def test_daily_resume_rebuild_posts_real_risks():
    cp = _cp()
    thread = "acme:daily:external"
    graph_a = build_report_graph(deps=_daily_deps(_ShortSpy()), audience="external",
                                 checkpointer=cp)
    graph_a.invoke({}, _cfg(thread))  # pause at the gate

    spy_b = _ShortSpy()
    graph_b = build_report_graph(deps=_daily_deps(spy_b), audience="external", checkpointer=cp)
    graph_b.invoke(Command(resume="approve"), _cfg(thread))  # FRESH box

    assert spy_b.calls == 1
    assert "⚠️" in spy_b.posted_short  # reflects the actual high risk
    assert "không phát hiện rủi ro" not in spy_b.posted_short  # NOT the degraded empty short


# --- okr: resume must NOT KeyError box["rollup"] + post the real rollup's short ---


def _rollup() -> OkrRollup:
    obj = Objective(name="Tăng retention",
                    key_results=(KeyResult("KR1", ("ABC-1",), 0.7, progress_pct=80.0),),
                    progress_pct=80.0)
    return OkrRollup(objectives=(obj,), problems=(OkrProblem("O1", "x"),),
                     at_risk=("Tăng retention",))


def _okr_deps(spy):
    return OkrReportDeps(
        fetch_rollup=_rollup,
        compose=lambda r: ("<p>okr</p>", None,
                          build_okr_slack_short(r, report_date="2026-06-25", detail_url=None,
                                                audience="external")),
        deliver=spy,
    )


def test_okr_resume_rebuild_posts_real_rollup():
    cp = _cp()
    thread = "acme:okr:external"
    build_okr_graph(deps=_okr_deps(_ShortSpy()), audience="external",
                    checkpointer=cp).invoke({}, _cfg(thread))

    spy_b = _ShortSpy()
    build_okr_graph(deps=_okr_deps(spy_b), audience="external", checkpointer=cp).invoke(
        Command(resume="approve"), _cfg(thread))

    assert spy_b.calls == 1  # would KeyError pre-fix
    assert "OKR Status" in spy_b.posted_short  # from the checkpointed short, not box


# --- resource: resume must NOT KeyError box["snapshot"] ---


def _resource_deps(spy, audience="internal"):
    resource = ResourceReport((AssigneeLoad("Carol", 6, 2, 1, overloaded=True),), 4.0,
                              ("Carol",), 1)
    cost = CostSummary(45.0, 50.0, 0.9, "warn", 200.0, 8, 25.0)
    return ResourceReportDeps(
        fetch=lambda: (resource, cost),
        compose=lambda r, c: ("<p>rc</p>", None,
                             build_resource_slack_short(r, c, report_date="2026-06-25",
                                                        detail_url=None, audience=audience)),
        deliver=spy,
    )


def test_resource_resume_rebuild_posts_real_snapshot():
    cp = _cp()
    thread = "acme:resource:external"
    build_resource_graph(deps=_resource_deps(_ShortSpy(), "external"), audience="external",
                         checkpointer=cp).invoke({}, _cfg(thread))

    spy_b = _ShortSpy()
    build_resource_graph(deps=_resource_deps(spy_b, "external"), audience="external",
                         checkpointer=cp).invoke(Command(resume="approve"), _cfg(thread))

    assert spy_b.calls == 1  # would KeyError pre-fix
    assert "nguồn lực" in spy_b.posted_short.lower() or "Resource" in spy_b.posted_short


@pytest.mark.parametrize("kind", ["okr", "resource"])
def test_okr_resource_resume_rebuild_no_keyerror(kind):
    # The whole resume would raise KeyError pre-fix; assert it completes with a delivery.
    cp = _cp()
    thread = f"acme:{kind}:external"
    def build(spy):
        if kind == "okr":
            return build_okr_graph(deps=_okr_deps(spy), audience="external", checkpointer=cp)
        return build_resource_graph(deps=_resource_deps(spy, "external"), audience="external",
                                    checkpointer=cp)

    build(_ShortSpy()).invoke({}, _cfg(thread))
    out = build(_ShortSpy()).invoke(Command(resume="approve"), _cfg(thread))
    assert out["delivered"] is True
