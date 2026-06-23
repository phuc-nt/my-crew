"""Phase 3 OKR reporting graph: perceive → analyze → compose → deliver.

Mirrors `report_graph` but for OKR: perceive reads the OKR Confluence table +
each mapped epic's progress from Jira, analyze rolls up weighted Objective
progress, compose renders a deterministic XHTML table (with an optional LLM
narrative paragraph above it), and deliver creates a Confluence page + posts a
short Slack link — all through the SAME Action Gateway path (create page, then
post), so no new write authority is introduced.

Dependencies are injected via `OkrReportDeps` so the graph runs in tests with
fakes (no network, no key, no subprocess). State holds only primitives.
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
from src.agent.okr_analyzer import OkrRollup
from src.agent.okr_weekly_section import build_okr_rollup
from src.agent.state import ReportState
from src.profile.context import EMPTY, ProfileContext

if TYPE_CHECKING:
    from src.config.reporting_config import ReportingConfig
    from src.config.settings import Settings

logger = logging.getLogger(__name__)


@dataclass
class OkrReportDeps:
    """Injectable collaborators for the OKR report flow (real or fake)."""

    fetch_rollup: Callable[[], OkrRollup]
    compose: Callable[[OkrRollup], tuple[str, float | None]]
    deliver: Callable[[OkrRollup, str], tuple[bool, str]]


def _today_utc() -> date:
    return datetime.now(UTC).date()


def default_okr_deps(
    *,
    config: ReportingConfig,
    settings: Settings,
    audience: str = "internal",
    context: ProfileContext = EMPTY,
    gateway: ActionGateway | None = None,
) -> OkrReportDeps:
    """Wire the real OKR implementations. Lazy imports keep graph-build network-free.

    `audience="external"` uses a business-tone narrative + posts to the stakeholder
    channel (Lớp B). The deterministic OKR table is audience-neutral. `config`/
    `settings` are injected; no config singleton is read here.
    """
    from src.actions.confluence_write import create_report_page
    from src.actions.slack_write import deliver_report
    from src.agent.audience_delivery import (
        SLACK_OK_STATUSES,
        delivery_summary,
        resolve_audience_delivery,
    )
    from src.llm.client import LlmClient
    from src.llm.okr_report_prompt import (
        build_okr_narrative_messages,
        build_okr_slack_short,
        fallback_okr_narrative,
        render_okr_table_xhtml,
    )
    from src.llm.report_prompt import REPORT_TITLES

    gw = gateway or ActionGateway(
        settings, external_channels=config.slack_external_channels
    )
    llm_box: dict[str, object] = {}

    def _compose(rollup: OkrRollup) -> tuple[str, float | None]:
        report_date = _today_utc().isoformat()
        table = render_okr_table_xhtml(rollup, report_date=report_date)
        narrative, cost = _narrate(rollup, report_date)
        return narrative + table, cost

    def _narrate(rollup: OkrRollup, report_date: str) -> tuple[str, float | None]:
        """LLM 1-paragraph narrative; fall back to a templated line without a key."""
        try:
            llm = llm_box.get("llm")
            if llm is None:
                llm = LlmClient(settings)
                llm_box["llm"] = llm
            result = llm.complete(
                build_okr_narrative_messages(
                    rollup,
                    report_date=report_date,
                    audience=audience,
                    persona=context.persona,
                    project=context.project,
                    memory=context.memory,
                )
            )
            return result.content, result.cost_usd
        except Exception as exc:  # no key / LLM error → narrative is optional
            logger.warning("OKR narrative skipped (LLM unavailable): %s", exc)
            return fallback_okr_narrative(rollup, report_date=report_date, audience=audience), None

    def _deliver(rollup: OkrRollup, body: str) -> tuple[bool, str]:
        today = _today_utc().isoformat()
        channel, date_hint = resolve_audience_delivery(audience, "okr", today, config)
        title = f"{REPORT_TITLES['okr']} {today}"
        conf_result, page = create_report_page(
            title, body, gateway=gw, config=config, report_date=date_hint,
            rationale=f"scheduled OKR status report (detail, {audience})",
        )
        detail_url = page.url if page else None
        short = build_okr_slack_short(
            rollup, report_date=today, detail_url=detail_url, audience=audience
        )
        slack_result = deliver_report(
            short, gateway=gw, config=config, channel=channel, report_date=date_hint,
            rationale=f"OKR status report (short + link, {audience})",
        )
        ok = (
            conf_result.status in {"executed", "dry_run"}
            and slack_result.status in SLACK_OK_STATUSES
        )
        return ok, delivery_summary(conf_result.status, slack_result, detail_url)

    return OkrReportDeps(
        fetch_rollup=lambda: build_okr_rollup(config),
        compose=_compose,
        deliver=_deliver,
    )


def _make_okr_nodes(deps: OkrReportDeps):
    box: dict[str, OkrRollup] = {}

    def perceive(_state: ReportState) -> dict:
        box["rollup"] = deps.fetch_rollup()
        return {}

    def analyze_node(_state: ReportState) -> dict:
        rollup = box.get("rollup")
        # Serialize a primitive summary for state; the rollup stays in the box.
        return {"risks": _problems_to_dicts(rollup)}

    def compose_report(_state: ReportState) -> dict:
        text, cost = deps.compose(box["rollup"])
        return {"report_text": text, "cost_usd": cost}

    def deliver(state: ReportState) -> dict:
        delivered, summary = deps.deliver(box["rollup"], state.get("report_text", ""))
        return {"delivered": delivered, "delivery_summary": summary}

    return perceive, analyze_node, compose_report, deliver


def _problems_to_dicts(rollup: OkrRollup | None) -> list[dict]:
    """Primitive view of OKR problems for checkpoint-safe state."""
    if rollup is None:
        return []
    return [{"row": p.row, "reason": p.reason} for p in rollup.problems]


def build_okr_graph(
    checkpointer: SqliteSaver | None = None,
    *,
    config: ReportingConfig | None = None,
    settings: Settings | None = None,
    context: ProfileContext = EMPTY,
    deps: OkrReportDeps | None = None,
    audience: str = "internal",
) -> CompiledStateGraph:
    """Build + compile the OKR reporting graph. `deps` defaults to real wiring.

    When `deps` is None, `config` + `settings` are required (they wire the real
    collaborators); `context` carries the profile persona/project/memory (empty ⇒
    v1). A caller that injects `deps` need not pass them.
    """
    if deps is None:
        if config is None or settings is None:
            raise ValueError(
                "build_okr_graph needs config + settings when deps is not provided."
            )
        deps = default_okr_deps(
            config=config, settings=settings, context=context, audience=audience
        )
    resolved = deps
    perceive, analyze_node, compose_report, deliver = _make_okr_nodes(resolved)

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
