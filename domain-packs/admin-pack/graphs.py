"""admin-pack fleet graphs (v3 M8) — one parametrized builder, three report kinds.

Same `perceive → analyze → compose → deliver` shape as PM/HR, all core machinery
imported from `src/` unchanged (the pack-purity gate). Admin-specific: the fleet
ToolProvider (platform state), the three pure analyzers, and the narrative prompt
asset — all sibling `domain_pack_admin.*` modules.

Delivery is Slack-only (no Confluence detail page — fleet digests are short
operational notes). The Lớp B approval gate still applies to an external-audience run,
same as every other kind.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from functools import partial

from langgraph.graph import END, START, StateGraph

from src.actions.action_gateway import ActionGateway
from src.actions.slack_write import deliver_report
from src.agent.approval_gate import add_approval_gate, external_summary
from src.agent.audience_delivery import SLACK_OK_STATUSES, resolve_audience_delivery
from src.agent.memory_node import add_remember_node
from src.agent.state import ReportState
from src.llm.client import LlmClient
from src.profile.context import EMPTY


def _today_utc() -> date:
    return datetime.now(UTC).date()


def build_fleet_graph(
    kind: str,
    checkpointer=None, *, config=None, settings=None, context=EMPTY,
    audience="internal", store=None, remember=None, tools=None,
):
    """Build + compile one admin fleet report graph for `kind`."""
    if config is None or settings is None:
        raise ValueError("build_fleet_graph needs config + settings.")
    from src.packs.registry import PackRegistry

    pack = PackRegistry().load("admin")
    if tools is None:
        tools = pack.tools

    from domain_pack_admin.analyzers import (
        BUILDERS,
        fallback_fleet_narrative,
        render_fleet_slack,
    )
    from domain_pack_admin.prompts_build import build_admin_narrative_messages

    build = BUILDERS[kind]
    # The pack's slack-only allowlist MUST reach the runtime gateway — without it the
    # gateway falls back to the wider core default (confluence/jira writes included).
    gw = ActionGateway(
        settings,
        external_channels=config.slack_external_channels,
        mcp_allowlist=pack.allowlist or None,
    )
    box: dict[str, object] = {}
    llm_box: dict[str, object] = {}

    def perceive(_state: ReportState) -> dict:
        box["payload"] = tools.read(kind, config, settings)
        return {}

    def analyze_node(_state: ReportState) -> dict:
        report = build(box.get("payload", {}))  # pure aggregation
        box["report"] = report
        return {"risks": list(report.alerts)}  # checkpoint-safe dicts

    def compose_report(_state: ReportState) -> dict:
        report = box.get("report")
        report_date = _today_utc().isoformat()
        text = render_fleet_slack(report, report_date=report_date)
        narrative = _narrate(report, report_date)
        return {
            "report_text": f"{text}\n\n_{narrative}_",
            "cost_usd": llm_box.get("cost"),
            "slack_short": f"{text}\n\n_{narrative}_",
        }

    def _narrate(report, report_date: str) -> str:
        try:
            llm = llm_box.get("llm") or LlmClient(settings)
            llm_box["llm"] = llm
            result = llm.complete(
                build_admin_narrative_messages(
                    report, report_date=report_date, audience=audience,
                    persona=context.persona, project=context.project, memory=context.memory,
                )
            )
            llm_box["cost"] = result.cost_usd
            return result.content
        except Exception:  # noqa: BLE001 — narrative failure must not drop the numbers
            return fallback_fleet_narrative(report)

    def deliver(state: ReportState) -> dict:
        approved = state.get("approval_decision") == "approve"
        report_date = _today_utc().isoformat()
        channel, date_hint = resolve_audience_delivery(audience, kind, report_date, config)
        slack_result = deliver_report(
            state.get("slack_short", ""), gateway=gw, config=config, channel=channel,
            report_date=date_hint, rationale=f"admin fleet report ({kind}, {audience})",
            approved=approved,
        )
        ok = slack_result.status in SLACK_OK_STATUSES
        return {"delivered": ok, "delivery_summary": f"slack={slack_result.status}"}

    builder = StateGraph(ReportState)
    builder.add_node("perceive", perceive)
    builder.add_node("analyze", analyze_node)
    builder.add_node("compose_report", compose_report)
    builder.add_node("deliver", deliver)
    builder.add_edge(START, "perceive")
    builder.add_edge("perceive", "analyze")
    builder.add_edge("analyze", "compose_report")
    add_approval_gate(
        builder, audience=audience, summary=external_summary(kind, audience, config)
    )
    if remember is not None:
        add_remember_node(builder, remember)
    else:
        builder.add_edge("deliver", END)
    return builder.compile(checkpointer=checkpointer, store=store)


REPORT_KINDS = {
    "cost-rollup": partial(build_fleet_graph, "cost-rollup"),
    "guardrail-health": partial(build_fleet_graph, "guardrail-health"),
    "audit-digest": partial(build_fleet_graph, "audit-digest"),
}
