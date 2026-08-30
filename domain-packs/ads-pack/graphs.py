"""ads-pack ads-weekly graph (P6) — Meta Ads insight report, pushed via Telegram DM.

Mirrors personal-pack's push-graph shape (perceive → compose → deliver, Telegram-only,
no Slack/Confluence) rather than hr-pack's PM-shaped Slack+Confluence deliver: this is
an internal-only owner report (audience="external" is refused, same posture as
personal-pack — Meta ad spend is an internal business number, no stakeholder ledger
exists for it in the MVP). ZERO writes: `perceive` reads through `AdsToolProvider`
only; there is no deliver-side gateway write beyond the Telegram push itself.

The builder signature matches the uniform pack contract so the core dispatches
`ads-weekly` exactly like any other report kind.
"""

from __future__ import annotations

from datetime import UTC, datetime

from langgraph.graph import END, START, StateGraph

from my_crew.actions.action_gateway import ActionGateway
from my_crew.actions.telegram_write import send_telegram_message
from my_crew.agent.memory_node import add_remember_node
from my_crew.agent.state import ReportState
from my_crew.llm.client import LlmClient
from my_crew.profile.context import EMPTY

_OK_STATUSES = frozenset({"executed", "dry_run"})


def _today_utc() -> str:
    return datetime.now(UTC).date().isoformat()


def build_ads_weekly_graph(
    checkpointer=None, *, config=None, settings=None, context=EMPTY,
    audience="internal", store=None, remember=None, tools=None,
):
    """Build + compile the ads-weekly graph. `tools` is the ads ToolProvider (P6);
    None ⇒ resolve the ads pack's own provider so the graph is runnable standalone."""
    if config is None or settings is None:
        raise ValueError("build_ads_weekly_graph needs config + settings.")
    if audience == "external":
        # Ad spend/reach is an internal business number in the MVP — no stakeholder
        # channel exists for it (mirrors personal-pack's DM-only posture).
        raise ValueError("ads-weekly chỉ hỗ trợ audience internal trong MVP.")

    from my_crew.packs.registry import PackRegistry

    pack = PackRegistry().load("ads")
    if tools is None:
        tools = pack.tools

    from domain_pack_ads.analyzers import (
        build_ads_weekly,
        fallback_ads_weekly_narrative,
        render_ads_weekly_text,
    )

    # ZERO writes in the MVP, but every pack still builds its gateway with its OWN
    # (empty) allowlist — never fall back to the wider core default (same guard
    # comment as hr-pack/personal-pack: `pack.allowlist` must reach the gateway).
    gw = ActionGateway(
        settings, external_channels=config.slack_external_channels, mcp_allowlist=pack.allowlist,
    )
    box: dict[str, object] = {}

    def perceive(_state: ReportState) -> dict:
        box["rows"] = tools.read("ads-weekly", config, settings)
        return {}

    def analyze_node(_state: ReportState) -> dict:
        box["report"] = build_ads_weekly(box.get("rows"))
        return {}

    def compose_report(_state: ReportState) -> dict:
        report = box["report"]
        report_date = _today_utc()
        table = render_ads_weekly_text(report, report_date)
        narrative = _narrate(report, report_date)
        return {"report_text": f"{narrative}\n\n{table}"}

    def _narrate(report, report_date: str) -> str:
        try:
            llm = LlmClient(settings)
            system = pack.prompts.get("ads-weekly-system", "")
            if context.persona:
                system = f"{context.persona}\n\n{system}"
            result = llm.complete(
                [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": (
                            f"Ngày báo cáo: {report_date}\n"
                            f"Dữ liệu đã tính sẵn (không tự bịa số khác): "
                            f"available={report.available}, "
                            f"total_spend={report.total_spend}, total_reach={report.total_reach}, "
                            f"so_chien_dich={len(report.campaigns)}.\n"
                            "Viết 1-2 câu nhận xét ngắn gửi chủ doanh nghiệp."
                        ),
                    },
                ]
            )
            return result.content.strip() or fallback_ads_weekly_narrative(report)
        except Exception:  # noqa: BLE001 — a narrative failure must not drop the numeric table
            return fallback_ads_weekly_narrative(report)

    def deliver(state: ReportState) -> dict:
        telegram = getattr(config, "telegram", None)
        chat_id = ""
        if telegram is not None:
            chat_ids = tuple(getattr(telegram, "chat_ids", ()) or ())
            operator = getattr(telegram, "ops_operator_id", "")
            chat_id = operator if operator in chat_ids else (chat_ids[0] if chat_ids else "")
        if not telegram or not chat_id:
            return {"delivered": False, "delivery_summary": "telegram=not_configured"}
        result = send_telegram_message(
            state.get("report_text", ""),
            gateway=gw, telegram=telegram, chat_id=str(chat_id),
            dedup_hint=f"ads-weekly:{chat_id}:{_today_utc()}",
            rationale="ads-weekly report (Meta Ads insight, internal)",
        )
        ok = result.status in _OK_STATUSES
        return {"delivered": ok, "delivery_summary": f"telegram={result.status}"}

    builder = StateGraph(ReportState)
    builder.add_node("perceive", perceive)
    builder.add_node("analyze", analyze_node)
    builder.add_node("compose_report", compose_report)
    builder.add_node("deliver", deliver)
    builder.add_edge(START, "perceive")
    builder.add_edge("perceive", "analyze")
    builder.add_edge("analyze", "compose_report")
    builder.add_edge("compose_report", "deliver")
    if remember is not None:
        add_remember_node(builder, remember)
    else:
        builder.add_edge("deliver", END)
    return builder.compile(checkpointer=checkpointer, store=store)


REPORT_KINDS = {"ads-weekly": build_ads_weekly_graph}
