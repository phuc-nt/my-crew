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
from typing import TYPE_CHECKING

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.actions.action_gateway import ActionGateway
from src.actions.slack_write import deliver_report
from src.agent.approval_gate import add_approval_gate, external_summary
from src.agent.risk_analyzer import analyze
from src.agent.state import ReportState
from src.llm.client import LlmClient
from src.profile.context import EMPTY, ProfileContext
from src.tools.models import CiRun, Issue, PullRequest, Risk

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore

    from src.config.reporting_config import ReportingConfig
    from src.config.settings import Settings

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
    # compose returns (detail_body, cost, slack_short) — the short is built URL-free at
    # compose (M2-P6 S4) and checkpointed so deliver is resume-safe (model-free).
    compose: Callable[[list[Risk]], tuple[str, float | None, str]]
    # deliver takes the URL-free short (from state) + body + approved; it creates the
    # page, injects the real link, and posts. `approved` (M2-P5) runs the gateway's
    # already-approved path after a graph-interrupt resume.
    deliver: Callable[..., tuple[bool, str]]


def _today_utc() -> date:
    return datetime.now(UTC).date()


def default_report_deps(
    *,
    config: ReportingConfig,
    settings: Settings,
    report_kind: str = "daily",
    audience: str = "internal",
    context: ProfileContext = EMPTY,
    client: LlmClient | None = None,
    gateway: ActionGateway | None = None,
) -> ReportDeps:
    """Wire the real implementations for a report kind ("daily" | "weekly").

    Weekly pulls the active sprint's issues (instead of all open issues) and
    passes sprint context to the detail prompt. `audience="external"` composes a
    business-tone report and posts the Slack short to the stakeholder channel
    (routes through Lớp B). `config`/`settings` are injected; collaborators
    (gateway, LLM, fetchers, writers, section helpers) are built from them — no
    config singleton is read here. Lazy imports keep graph-build network-free.
    """
    from src.actions.confluence_write import create_report_page
    from src.llm.report_prompt import REPORT_TITLES, build_detail_messages, build_slack_short
    from src.tools import github_read, jira_read

    gw = gateway or ActionGateway(
        settings, external_channels=config.slack_external_channels
    )
    llm = client
    sprint_box: dict[str, object] = {}

    def _fetch_issues() -> list[Issue]:
        if report_kind == "weekly":
            sprint = jira_read.get_active_sprint(config=config)
            sprint_box["sprint"] = sprint
            if sprint is not None:
                return jira_read.get_sprint_issues(sprint.id, config=config)
            return jira_read.get_open_issues(config=config)  # fallback: no active sprint
        return jira_read.get_open_issues(config=config)

    def _sprint_context() -> str | None:
        sprint = sprint_box.get("sprint")
        if sprint is None:
            if report_kind == "weekly":
                return "Không có sprint active — dùng toàn bộ issue đang mở."
            return None
        return (
            f"Sprint: {sprint.name} ({sprint.state}), "
            f"{sprint.start_date} → {sprint.end_date}."
        )

    def _compose(risks: list[Risk]) -> tuple[str, float | None, str]:
        nonlocal llm
        if llm is None:
            llm = LlmClient(settings)
        today = _today_utc().isoformat()
        messages = build_detail_messages(
            risks,
            report_date=today,
            kind=report_kind,
            sprint_context=_sprint_context(),
            audience=audience,
            persona=context.persona,
            project=context.project,
            memory=context.memory,
        )
        result = llm.complete(messages)
        body = result.content
        # Weekly review also carries OKR + resource sections (internal only — these
        # are internal-detail noise an external stakeholder report should not embed).
        if report_kind == "weekly" and audience == "internal":
            from src.agent.okr_weekly_section import weekly_okr_section
            from src.agent.resource_weekly_section import weekly_resource_section

            body += weekly_okr_section(today, config)
            body += weekly_resource_section(today, config, settings)
        # Build the Slack short URL-free NOW (risks are live) and checkpoint it via state,
        # so deliver posts the correct short on resume without the closure box. The detail
        # link + the config-derived weekly lines are appended in deliver (resume-safe).
        short = build_slack_short(risks, report_date=today, detail_url=None, audience=audience)
        return body, result.cost_usd, short

    def _deliver(short_no_url: str, detail_body: str, approved: bool = False) -> tuple[bool, str]:
        from src.agent.audience_delivery import (
            SLACK_OK_STATUSES,
            delivery_summary,
            resolve_audience_delivery,
        )
        from src.llm.slack_link import inject_link

        today = _today_utc().isoformat()
        channel, date_hint = resolve_audience_delivery(audience, report_kind, today, config)
        title = f"{REPORT_TITLES.get(report_kind, 'Báo cáo')} {today}"
        # 1) Confluence detail page (through the gateway). dedup keyed per kind+audience+date.
        # `approved` runs the already-human-approved path after a graph-interrupt resume.
        conf_result, page = create_report_page(
            title,
            detail_body,
            gateway=gw,
            config=config,
            report_date=date_hint,
            rationale=f"scheduled {report_kind} progress report (detail, {audience})",
            approved=approved,
        )
        detail_url = page.url if page else None
        # 2) Slack short = the checkpointed URL-free short + the real link + weekly lines
        # (config-derived, so resume-safe). No model/box read here.
        short = inject_link(
            short_no_url, detail_url, text="Xem báo cáo chi tiết trên Confluence"
        )
        if report_kind == "weekly" and audience == "internal":
            from src.agent.okr_weekly_section import weekly_okr_slack_line
            from src.agent.resource_weekly_section import weekly_resource_slack_line

            short += weekly_okr_slack_line(config)
            short += weekly_resource_slack_line(config, settings)
        slack_result = deliver_report(
            short,
            gateway=gw,
            config=config,
            channel=channel,
            report_date=date_hint,
            rationale=f"{report_kind} progress report (short + link, {audience})",
            approved=approved,
        )
        ok = (
            conf_result.status in {"executed", "dry_run"}
            and slack_result.status in SLACK_OK_STATUSES
        )
        return ok, delivery_summary(conf_result.status, slack_result, detail_url)

    return ReportDeps(
        fetch_issues=_fetch_issues,
        fetch_prs=lambda: github_read.get_open_prs(config=config),
        fetch_ci=lambda: github_read.get_recent_ci(config=config),
        analyze_risks=lambda issues, prs, ci: analyze(
            issues, prs, ci, today=_today_utc(),
            blocker_label_substring=config.blocker_label_substring,
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
        # `report_text` holds the Confluence detail body (storage HTML). `slack_short`
        # is the URL-free short, checkpointed so deliver survives a resume (S4).
        text, cost, short = deps.compose(box.get("risks", []))
        return {"report_text": text, "cost_usd": cost, "slack_short": short}

    def deliver(state: ReportState) -> dict:
        # When the graph reached `deliver` via the approval_gate's approve branch
        # (M2-P5), the human already authorized this external post at the interrupt —
        # run the gateway's already-approved path so it posts live (not re-queued).
        # Reads ONLY state (report_text + slack_short) — resume-safe, no box.
        approved = state.get("approval_decision") == "approve"
        delivered, summary = deps.deliver(
            state.get("slack_short", ""), state.get("report_text", ""), approved
        )
        return {"delivered": delivered, "delivery_summary": summary}

    return perceive, analyze_node, compose_report, deliver


def _risks_to_dicts(risks: list[Risk]) -> list[dict]:
    """Serialize risks for graph state (checkpointer-safe primitives)."""
    from dataclasses import asdict

    return [asdict(r) for r in risks]


def build_report_graph(
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    config: ReportingConfig | None = None,
    settings: Settings | None = None,
    context: ProfileContext = EMPTY,
    deps: ReportDeps | None = None,
    report_kind: str = "daily",
    audience: str = "internal",
    store: BaseStore | None = None,
    remember=None,
) -> CompiledStateGraph:
    """Build + compile the reporting graph. `deps` defaults to real wiring.

    `report_kind` ("daily" | "weekly") selects the data scope + prompt framing;
    `audience` ("internal" | "external") selects the tone + delivery channel — both
    when `deps` is not explicitly provided. `context` carries the profile's
    persona/project/memory (empty ⇒ v1 prompts). When `deps` is None, `config` +
    `settings` are required; a caller that injects `deps` need not pass them.
    """
    if deps is None:
        if config is None or settings is None:
            raise ValueError(
                "build_report_graph needs config + settings when deps is not provided."
            )
        deps = default_report_deps(
            config=config,
            settings=settings,
            context=context,
            report_kind=report_kind,
            audience=audience,
        )
    resolved = deps
    perceive, analyze_node, compose_report, deliver = _make_nodes(resolved)

    builder = StateGraph(ReportState)
    builder.add_node("perceive", perceive)
    builder.add_node("analyze", analyze_node)
    builder.add_node("compose_report", compose_report)
    builder.add_node("deliver", deliver)
    builder.add_edge(START, "perceive")
    builder.add_edge("perceive", "analyze")
    builder.add_edge("analyze", "compose_report")
    # M2-P5: Lớp B graph-native interrupt. The gate sits between compose and deliver;
    # external audience pauses here for human approval (resume routes to deliver/END).
    # Internal audience is a pass-through, so the edge is effectively compose→deliver.
    add_approval_gate(
        builder,
        audience=audience,
        summary=external_summary(report_kind, audience, config),
    )
    # M2-P8: a `remember` node after deliver extracts + persists agent memory (internal
    # runs only — the node self-gates). When no remember node is injected, deliver → END.
    if remember is not None:
        from src.agent.memory_node import add_remember_node

        add_remember_node(builder, remember)
    else:
        builder.add_edge("deliver", END)
    return builder.compile(checkpointer=checkpointer, store=store)
