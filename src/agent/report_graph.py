"""Phase 1 reporting graph: perceive → analyze → compose_report → deliver.

Reads Jira (MCP) + GitHub (gh), detects risks, has the LLM compose a report, and
posts it to Slack through the Action Gateway. All external dependencies are
injected via `ReportDeps` so the graph runs in tests with fakes (no network, no
key, no subprocess). The default deps wire the real implementations.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.actions.action_gateway import ActionGateway
from src.actions.slack_write import deliver_report
from src.agent.risk_analyzer import analyze
from src.agent.state import ReportState
from src.llm.client import LlmClient
from src.tools.models import CiRun, Issue, PullRequest, Risk

logger = logging.getLogger(__name__)


@dataclass
class ReportDeps:
    """Injectable collaborators for the report flow (real or fake).

    Slice 2: `compose` produces the Confluence detail body (storage HTML);
    `deliver` takes (risks, detail_body) and does the two writes — create the
    Confluence page, then post a short Slack message linking to it.
    """

    fetch_issues: Callable[[], list[Issue]]
    fetch_prs: Callable[[], list[PullRequest]]
    fetch_ci: Callable[[], list[CiRun]]
    analyze_risks: Callable[[list[Issue], list[PullRequest], list[CiRun]], list[Risk]]
    compose: Callable[[list[Risk]], tuple[str, float | None]]
    deliver: Callable[[list[Risk], str], tuple[bool, str]]


def _today_utc() -> date:
    return datetime.now(UTC).date()


def default_report_deps(
    *, client: LlmClient | None = None, gateway: ActionGateway | None = None
) -> ReportDeps:
    """Wire the real implementations (lazy imports keep graph-build network-free)."""
    from src.actions.confluence_write import create_report_page
    from src.config.reporting_config import get_reporting_config
    from src.llm.report_prompt import build_detail_messages, build_slack_short
    from src.tools import github_read, jira_read

    cfg = get_reporting_config()
    gw = gateway or ActionGateway()
    llm = client

    def _compose(risks: list[Risk]) -> tuple[str, float | None]:
        """Compose the Confluence detail body (storage HTML) via one LLM call."""
        nonlocal llm
        if llm is None:
            llm = LlmClient()
        messages = build_detail_messages(risks, report_date=_today_utc().isoformat())
        result = llm.complete(messages)
        return result.content, result.cost_usd

    def _deliver(risks: list[Risk], detail_body: str) -> tuple[bool, str]:
        today = _today_utc().isoformat()
        # 1) Confluence detail page (through the gateway).
        conf_result, page = create_report_page(
            f"Báo cáo tiến độ {today}",
            detail_body,
            gateway=gw,
            report_date=today,
            rationale="scheduled/triggered progress report (detail)",
        )
        detail_url = page.url if page else None
        # 2) Slack short message + link (through the gateway), derived from risks.
        short = build_slack_short(risks, report_date=today, detail_url=detail_url)
        slack_result = deliver_report(
            short, gateway=gw, report_date=today, rationale="progress report (short + link)"
        )
        ok = (
            conf_result.status in {"executed", "dry_run"}
            and slack_result.status in {"executed", "dry_run", "deduplicated"}
        )
        return ok, f"confluence={conf_result.status} slack={slack_result.status} url={detail_url}"

    return ReportDeps(
        fetch_issues=lambda: jira_read.get_open_issues(),
        fetch_prs=lambda: github_read.get_open_prs(),
        fetch_ci=lambda: github_read.get_recent_ci(),
        analyze_risks=lambda issues, prs, ci: analyze(
            issues, prs, ci, today=_today_utc(),
            blocker_label_substring=cfg.blocker_label_substring,
        ),
        compose=_compose,
        deliver=_deliver,
    )


def _make_nodes(deps: ReportDeps):
    # Heavy fetched models (Issue/PR/CiRun) are kept in this closure, NOT in graph
    # state, so the checkpointer only persists serializable primitives. `risks` is
    # stored in state as plain dicts (see _risks_to_dicts / Risk(**d)).
    box: dict[str, list] = {}

    def perceive(_state: ReportState) -> dict:
        box["issues"] = deps.fetch_issues()
        box["prs"] = deps.fetch_prs()
        box["ci"] = deps.fetch_ci()
        return {}

    def analyze_node(_state: ReportState) -> dict:
        risks = deps.analyze_risks(box.get("issues", []), box.get("prs", []), box.get("ci", []))
        box["risks"] = risks
        return {"risks": _risks_to_dicts(risks)}

    def compose_report(_state: ReportState) -> dict:
        # `report_text` holds the Confluence detail body (storage HTML) in Slice 2.
        text, cost = deps.compose(box.get("risks", []))
        return {"report_text": text, "cost_usd": cost}

    def deliver(state: ReportState) -> dict:
        delivered, summary = deps.deliver(box.get("risks", []), state.get("report_text", ""))
        return {"delivered": delivered, "delivery_summary": summary}

    return perceive, analyze_node, compose_report, deliver


def _risks_to_dicts(risks: list[Risk]) -> list[dict]:
    """Serialize risks for graph state (checkpointer-safe primitives)."""
    from dataclasses import asdict

    return [asdict(r) for r in risks]


def build_report_graph(
    checkpointer: SqliteSaver | None = None, *, deps: ReportDeps | None = None
) -> CompiledStateGraph:
    """Build + compile the reporting graph. `deps` defaults to real wiring."""
    resolved = deps or default_report_deps()
    perceive, analyze_node, compose_report, deliver = _make_nodes(resolved)

    builder = StateGraph(ReportState)
    builder.add_node("perceive", perceive)
    builder.add_node("analyze", analyze_node)
    builder.add_node("compose_report", compose_report)
    builder.add_node("deliver", deliver)
    builder.add_edge(START, "perceive")
    builder.add_edge("perceive", "analyze")
    builder.add_edge("analyze", "compose_report")
    builder.add_edge("compose_report", "deliver")
    builder.add_edge("deliver", END)
    return builder.compile(checkpointer=checkpointer)
