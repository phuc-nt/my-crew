"""Phase 4 resource + cost reporting graph: perceive → analyze → compose → deliver.

Mirrors `okr_report_graph`: perceive reads open Jira issues + the LLM budget,
analyze builds the per-assignee load report + cost summary, compose renders
deterministic tables (with an optional LLM narrative above), and deliver creates a
Confluence page + posts a Slack link through the SAME Action Gateway path — so no
new write authority is introduced. Dedup key `resource-<date>`.

The single fetch+analyze entry `build_resource_rollup` lives in
`resource_weekly_section` and is shared with the weekly-embedded section (the OKR
precedent). State holds only primitives.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.actions.action_gateway import ActionGateway
from src.agent.resource_weekly_section import build_resource_rollup
from src.agent.state import ReportState
from src.tools.models import CostSummary, ResourceReport

if TYPE_CHECKING:
    from src.config.reporting_config import ReportingConfig
    from src.config.settings import Settings

logger = logging.getLogger(__name__)

Snapshot = tuple[ResourceReport, CostSummary]


@dataclass
class ResourceReportDeps:
    """Injectable collaborators for the resource + cost report flow (real or fake)."""

    fetch: Callable[[], Snapshot]
    compose: Callable[[ResourceReport, CostSummary], tuple[str, float | None]]
    deliver: Callable[[ResourceReport, CostSummary, str], tuple[bool, str]]


def _today_utc() -> date:
    return datetime.now(UTC).date()


def default_resource_deps(
    *,
    config: ReportingConfig,
    settings: Settings,
    audience: str = "internal",
    gateway: ActionGateway | None = None,
) -> ResourceReportDeps:
    """Wire the real resource implementations. Lazy imports keep graph-build network-free.

    `audience="external"` uses a names-free, labor-free business narrative + short and
    posts to the stakeholder channel (Lớp B). The internal Confluence table is unchanged.
    `config`/`settings` are injected; no config singleton is read here.
    """
    from src.actions.confluence_write import create_report_page
    from src.actions.slack_write import deliver_report
    from src.agent.audience_delivery import (
        SLACK_OK_STATUSES,
        delivery_summary,
        resolve_audience_delivery,
    )
    from src.llm.client import LlmClient
    from src.llm.report_prompt import REPORT_TITLES
    from src.llm.resource_report_prompt import (
        build_resource_narrative_messages,
        build_resource_slack_short,
        fallback_resource_narrative,
        render_resource_xhtml,
    )

    gw = gateway or ActionGateway(
        settings, external_channels=config.slack_external_channels
    )
    llm_box: dict[str, object] = {}

    def _compose(resource: ResourceReport, cost: CostSummary) -> tuple[str, float | None]:
        report_date = _today_utc().isoformat()
        table = render_resource_xhtml(resource, cost, report_date=report_date)
        narrative, usd = _narrate(resource, cost, report_date)
        return narrative + table, usd

    def _narrate(
        resource: ResourceReport, cost: CostSummary, report_date: str
    ) -> tuple[str, float | None]:
        try:
            llm = llm_box.get("llm")
            if llm is None:
                llm = LlmClient(settings)
                llm_box["llm"] = llm
            result = llm.complete(
                build_resource_narrative_messages(
                    resource, cost, report_date=report_date, audience=audience
                )
            )
            return result.content, result.cost_usd
        except Exception as exc:  # no key / LLM error → narrative is optional
            logger.warning("Resource narrative skipped (LLM unavailable): %s", exc)
            return (
                fallback_resource_narrative(
                    resource, cost, report_date=report_date, audience=audience
                ),
                None,
            )

    def _deliver(resource: ResourceReport, cost: CostSummary, body: str) -> tuple[bool, str]:
        today = _today_utc().isoformat()
        channel, date_hint = resolve_audience_delivery(audience, "resource", today, config)
        title = f"{REPORT_TITLES['resource']} {today}"
        conf_result, page = create_report_page(
            title, body, gateway=gw, config=config, report_date=date_hint,
            rationale=f"scheduled resource & cost status report (detail, {audience})",
        )
        detail_url = page.url if page else None
        # The resource Confluence page carries the per-assignee table (names, counts,
        # labor cost). For an external audience we must NOT hand that link to the
        # stakeholder — the short stays the high-level capacity summary only.
        short_url = None if audience == "external" else detail_url
        short = build_resource_slack_short(
            resource, cost, report_date=today, detail_url=short_url, audience=audience
        )
        slack_result = deliver_report(
            short, gateway=gw, config=config, channel=channel, report_date=date_hint,
            rationale=f"resource & cost status report (short + link, {audience})",
        )
        ok = (
            conf_result.status in {"executed", "dry_run"}
            and slack_result.status in SLACK_OK_STATUSES
        )
        return ok, delivery_summary(conf_result.status, slack_result, detail_url)

    return ResourceReportDeps(
        fetch=lambda: build_resource_rollup(config, settings),
        compose=_compose,
        deliver=_deliver,
    )


def _make_resource_nodes(deps: ResourceReportDeps):
    box: dict[str, Snapshot] = {}

    def perceive(_state: ReportState) -> dict:
        box["snapshot"] = deps.fetch()
        return {}

    def analyze_node(_state: ReportState) -> dict:
        resource, _cost = box["snapshot"]
        # Primitive summary for checkpoint-safe state; the snapshot stays in the box.
        return {"risks": [{"assignee": name} for name in resource.overloaded]}

    def compose_report(_state: ReportState) -> dict:
        resource, cost = box["snapshot"]
        text, usd = deps.compose(resource, cost)
        return {"report_text": text, "cost_usd": usd}

    def deliver(state: ReportState) -> dict:
        resource, cost = box["snapshot"]
        delivered, summary = deps.deliver(resource, cost, state.get("report_text", ""))
        return {"delivered": delivered, "delivery_summary": summary}

    return perceive, analyze_node, compose_report, deliver


def build_resource_graph(
    checkpointer: SqliteSaver | None = None,
    *,
    config: ReportingConfig | None = None,
    settings: Settings | None = None,
    deps: ResourceReportDeps | None = None,
    audience: str = "internal",
) -> CompiledStateGraph:
    """Build + compile the resource + cost reporting graph. `deps` defaults to real wiring.

    When `deps` is None, `config` + `settings` are required (they wire the real
    collaborators); a caller that injects `deps` need not pass them.
    """
    if deps is None:
        if config is None or settings is None:
            raise ValueError(
                "build_resource_graph needs config + settings when deps is not provided."
            )
        deps = default_resource_deps(config=config, settings=settings, audience=audience)
    resolved = deps
    perceive, analyze_node, compose_report, deliver = _make_resource_nodes(resolved)

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
