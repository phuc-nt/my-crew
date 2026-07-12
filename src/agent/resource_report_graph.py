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

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.actions.action_gateway import ActionGateway
from src.agent.approval_gate import add_approval_gate, external_summary
from src.agent.resource_weekly_section import build_resource_rollup
from src.agent.sibling_selector import select_sibling_text
from src.agent.state import ReportState
from src.company_docs.inject import company_docs_text
from src.profile.context import EMPTY, ProfileContext
from src.skills.skill_selector import select_skill_text
from src.tools.models import CostSummary, ResourceReport

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore

    from src.config.reporting_config import ReportingConfig
    from src.config.settings import Settings

logger = logging.getLogger(__name__)

Snapshot = tuple[ResourceReport, CostSummary]


@dataclass
class ResourceReportDeps:
    """Injectable collaborators for the resource + cost report flow (real or fake)."""

    fetch: Callable[[], Snapshot]
    # compose returns (body, cost, slack_short) — short built URL-free, checkpointed (S4).
    compose: Callable[[ResourceReport, CostSummary], tuple[str, float | None, str]]
    # deliver takes the URL-free short (from state) + body + approved (model-free) +
    # attachment_path (the .xlsx built at compose, threaded via state — resume-safe).
    # `approved` (M2-P5): True when the graph resumed past the Lớp B interrupt with
    # an approve decision — the writers then run the gateway's already-approved path.
    deliver: Callable[..., tuple[bool, str]]
    # build_xlsx writes the report .xlsx into the artifact dir and returns its path
    # (a str) — or None when no email channel is configured (skip the orphan file).
    # Called at compose (snapshot live in the box); only the path string enters state.
    build_xlsx: Callable[[ResourceReport, CostSummary], str | None] | None = None


def _today_utc() -> date:
    return datetime.now(UTC).date()


def default_resource_deps(
    *,
    config: ReportingConfig,
    settings: Settings,
    audience: str = "internal",
    context: ProfileContext = EMPTY,
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

    # Resource is a PM-only report kind → core default allowlist (== PM pack's). No
    # non-PM pack serves this kind, so there is no pack allowlist to thread here (unlike
    # the daily/weekly report graph). Thread it like S4 does if that ever changes.
    gw = gateway or ActionGateway(
        settings, external_channels=config.slack_external_channels,
        auto_approve=getattr(context, "auto_approve", None),  # v8 M23
    )
    llm_box: dict[str, object] = {}

    def _compose(
        resource: ResourceReport, cost: CostSummary
    ) -> tuple[str, float | None, str]:
        report_date = _today_utc().isoformat()
        table = render_resource_xhtml(resource, cost, report_date=report_date)
        narrative, usd = _narrate(resource, cost, report_date)
        # URL-free short built here (snapshot live) + checkpointed → resume-safe (S4).
        short = build_resource_slack_short(resource, cost, report_date=report_date,
                                           detail_url=None, audience=audience)
        return narrative + table, usd, short

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
                    resource,
                    cost,
                    report_date=report_date,
                    audience=audience,
                    persona=context.persona,
                    project=context.project,
                    memory=context.memory,
                    skills=select_skill_text(context, audience, kind="resource"),
                    company_docs=company_docs_text(context, audience),
                    sibling_facts=select_sibling_text(
                        context, audience, kind="resource", project_group=context.sibling_project
                    ),
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

    def _build_xlsx(resource: ResourceReport, cost: CostSummary) -> str | None:
        # Only write the file when email is actually configured — no email channel means
        # no attachment consumer, so skip the orphan artifact. The file lands in the same
        # artifact dir Lớp A confines attachments to (gw.artifact_root).
        from src.agent.channel_registry import resolve_channels

        if "email" not in resolve_channels(config):
            return None
        from src.reporting.xlsx_export import artifact_path, build_resource_xlsx

        report_date = _today_utc().isoformat()
        path = artifact_path(settings.data_dir, "resource", report_date)
        path.write_bytes(build_resource_xlsx(resource, cost, report_date=report_date))
        return str(path)

    def _deliver(
        short_no_url: str, body: str, approved: bool = False,
        attachment_path: str | None = None,
    ) -> tuple[bool, str]:
        from src.llm.slack_link import inject_link

        today = _today_utc().isoformat()
        channel, date_hint = resolve_audience_delivery(audience, "resource", today, config)
        title = f"{REPORT_TITLES['resource']} {today}"
        conf_result, page = create_report_page(
            title, body, gateway=gw, config=config, report_date=date_hint,
            rationale=f"scheduled resource & cost status report (detail, {audience})",
            approved=approved,
        )
        detail_url = page.url if page else None
        # The resource Confluence page carries the per-assignee table (names, counts,
        # labor cost). For an external audience we must NOT hand that link to the
        # stakeholder — inject_link(short, None) leaves the short link-free (gate kept).
        short_url = None if audience == "external" else detail_url
        short = inject_link(short_no_url, short_url, text="Xem chi tiết trên Confluence")
        slack_result = deliver_report(
            short, gateway=gw, config=config, channel=channel, report_date=date_hint,
            rationale=f"resource & cost status report (short + link, {audience})",
            approved=approved,
        )
        ok = (
            conf_result.status in {"executed", "dry_run"}
            and slack_result.status in SLACK_OK_STATUSES
        )
        from src.agent.audience_delivery import deliver_extra_channels_and_summarize

        extra = deliver_extra_channels_and_summarize(
            body, title, gateway=gw, config=config, report_date=date_hint,
            audience=audience, rationale=f"resource report ({audience})", approved=approved,
            attachment_path=attachment_path,
        )
        return ok, delivery_summary(conf_result.status, slack_result, detail_url) + extra

    return ResourceReportDeps(
        fetch=lambda: build_resource_rollup(config, settings),
        compose=_compose,
        deliver=_deliver,
        build_xlsx=_build_xlsx,
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
        text, usd, short = deps.compose(resource, cost)
        out: dict = {"report_text": text, "cost_usd": usd, "slack_short": short}
        # Build the .xlsx here (snapshot live in the box) and thread only its PATH
        # through state — resume-safe (S4), never the dataclass or bytes.
        if deps.build_xlsx is not None:
            xlsx_path = deps.build_xlsx(resource, cost)
            if xlsx_path is not None:
                out["xlsx_path"] = xlsx_path
        return out

    def deliver(state: ReportState) -> dict:
        # M2-P5: approve at the interrupt authorizes the live external post.
        # Reads ONLY state (S4) — resume-safe, no box["snapshot"].
        approved = state.get("approval_decision") == "approve"
        delivered, summary = deps.deliver(
            state.get("slack_short", ""), state.get("report_text", ""), approved,
            state.get("xlsx_path"),
        )
        return {"delivered": delivered, "delivery_summary": summary}

    return perceive, analyze_node, compose_report, deliver


def build_resource_graph(
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    config: ReportingConfig | None = None,
    settings: Settings | None = None,
    context: ProfileContext = EMPTY,
    deps: ResourceReportDeps | None = None,
    audience: str = "internal",
    store: BaseStore | None = None,
    remember=None,
) -> CompiledStateGraph:
    """Build + compile the resource + cost reporting graph. `deps` defaults to real wiring.

    When `deps` is None, `config` + `settings` are required (they wire the real
    collaborators); `context` carries the profile persona/project/memory (empty ⇒
    v1). A caller that injects `deps` need not pass them.
    """
    if deps is None:
        if config is None or settings is None:
            raise ValueError(
                "build_resource_graph needs config + settings when deps is not provided."
            )
        deps = default_resource_deps(
            config=config, settings=settings, context=context, audience=audience
        )
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
    # M2-P5: Lớp B graph-native interrupt for external audience (see report_graph).
    add_approval_gate(
        builder, audience=audience, summary=external_summary("resource", audience, config),
        report_kind="resource", auto_approve=getattr(context, "auto_approve", None),
        settings=settings,
    )
    # M2-P8: `remember` node after deliver (internal runs only; self-gates). See report_graph.
    if remember is not None:
        from src.agent.memory_node import add_remember_node

        add_remember_node(builder, remember)
    else:
        builder.add_edge("deliver", END)
    return builder.compile(checkpointer=checkpointer, store=store)
