"""personal-pack push graphs (v57) — briefing ngày + weekly-review, chủ động qua Telegram DM.

perceive (bối cảnh ngày từ ToolProvider) → compose (LLM viết bản tin, persona/trí nhớ
từ context; LLM hỏng → fallback thuần code vẫn ship được ngày giờ) → deliver (DM Telegram
của chính agent qua Action Gateway — dry-run/kill-switch/secret-scan/dedup nguyên vẹn).

Khác các pack báo cáo: KHÔNG có ngả external. Thư ký chỉ nói với chủ nhân qua DM
allowlist; audience "external" fail loud thay vì lặng lẽ đổi kênh (bản tin chứa trí nhớ
cá nhân — không bao giờ được rơi ra stakeholder channel).
"""

from __future__ import annotations

from datetime import datetime

from langgraph.graph import END, START, StateGraph

from my_crew.actions.action_gateway import ActionGateway
from my_crew.actions.telegram_write import send_telegram_message
from my_crew.agent.memory_node import add_remember_node
from my_crew.agent.qa_answer import render_snapshot
from my_crew.agent.state import ReportState
from my_crew.llm.client import LlmClient
from my_crew.profile.context import EMPTY

#: Kết quả gateway coi là "đã giao" — dry_run tính là giao (hành vi chuẩn mọi pack).
_OK_STATUSES = frozenset({"executed", "dry_run"})


def _giao_buoi(hour: int) -> str:
    if hour < 11:
        return "sáng"
    if hour < 14:
        return "trưa"
    if hour < 18:
        return "chiều"
    return "tối"


def _fallback_briefing(snapshot: dict) -> str:
    """Bản tin thuần code khi LLM hỏng — vẫn hữu ích (ngày giờ), không bịa gì thêm."""
    now = datetime.now().astimezone()
    return (
        f"Chào buổi {_giao_buoi(now.hour)}! Hôm nay là {snapshot.get('thu', '')}, "
        f"{now.strftime('%d/%m/%Y')}.\n"
        f"(Trợ lý soạn tin đang lỗi — đây là bản tin rút gọn. "
        f"{snapshot.get('ghi_chu', '')})"
    )


#: Câu chốt trong user message + rationale audit — điểm khác nhau duy nhất giữa 2 kind
#: về mặt "viết gì" nằm ở prompt `<kind>-system` và dòng lệnh cuối này.
_KIND_INSTRUCTION = {
    "briefing": "Viết bản tin gửi chủ nhân bây giờ.",
    "weekly-review": "Viết bản nhìn lại tuần gửi chủ nhân bây giờ.",
}
_KIND_RATIONALE = {
    "briefing": "Bản tin thư ký riêng gửi chủ nhân",
    "weekly-review": "Bản nhìn lại tuần thư ký riêng gửi chủ nhân",
}


def _build_push_graph(
    kind, checkpointer=None, *, config=None, settings=None, context=EMPTY,
    audience="internal", store=None, remember=None, tools=None,
):
    """Build + compile graph đẩy-Telegram cho một kind. Chữ ký khớp contract pack chung."""
    if config is None or settings is None:
        raise ValueError(f"build graph {kind!r} needs config + settings.")
    if audience != "internal":
        # Bản tin thư ký mang trí nhớ cá nhân của chủ nhân — không tồn tại ngả external.
        raise ValueError("bản tin của thư ký chỉ có audience internal.")
    from my_crew.packs.registry import PackRegistry

    pack = PackRegistry().load("personal")
    if tools is None:
        tools = pack.tools

    # KHÔNG dùng `pack.allowlist or None`: allowlist rỗng CÓ CHỦ ĐÍCH — `or None` sẽ
    # âm thầm hồi sinh allowlist mặc định rộng của core (bẫy office-pack đã cảnh báo).
    gw = ActionGateway(
        settings,
        external_channels=config.slack_external_channels,
        mcp_allowlist=pack.allowlist,
    )
    box: dict[str, object] = {}

    def perceive(_state: ReportState) -> dict:
        box["snapshot"] = tools.read(kind, config, settings)
        return {}

    def compose_report(_state: ReportState) -> dict:
        snapshot = box.get("snapshot") or {}
        system = pack.prompts.get(f"{kind}-system", "")
        if context.persona:
            system = f"{context.persona}\n\n{system}"
        user_parts = []
        if context.memory:
            user_parts.append(f"TRÍ NHỚ:\n{context.memory}")
        if context.project:
            user_parts.append(f"BỐI CẢNH:\n{context.project}")
        user_parts.append(f"DATA:\n{render_snapshot(snapshot)}")
        user_parts.append(_KIND_INSTRUCTION[kind])
        try:
            llm = LlmClient(settings)
            result = llm.complete([
                {"role": "system", "content": system},
                {"role": "user", "content": "\n\n".join(user_parts)},
            ])
            text = result.content.strip() or _fallback_briefing(snapshot)
            return {"report_text": text, "cost_usd": result.cost_usd}
        except Exception:  # noqa: BLE001 — LLM hỏng không được nuốt mất bản tin
            return {"report_text": _fallback_briefing(snapshot), "cost_usd": None}

    def deliver(state: ReportState) -> dict:
        telegram = getattr(config, "telegram", None)
        chat_id = ""
        if telegram is not None:
            chat_ids = tuple(getattr(telegram, "chat_ids", ()) or ())
            operator = getattr(telegram, "ops_operator_id", "")
            # ops_operator_id là USER id — chỉ dùng làm đích khi nó nằm trong allowlist
            # chat_ids (DM); lệch nhau thì handler sẽ PermissionError mỗi tick → tránh.
            chat_id = operator if operator in chat_ids else (chat_ids[0] if chat_ids else "")
        if not telegram or not chat_id:
            # Agent chưa gắn Telegram — skip có tiếng, không crash tick.
            return {"delivered": False, "delivery_summary": "telegram=not_configured"}
        local_date = datetime.now().astimezone().date().isoformat()
        result = send_telegram_message(
            state.get("report_text", ""),
            gateway=gw,
            telegram=telegram,
            chat_id=str(chat_id),
            # Kind nằm trong hint: briefing và weekly-review cùng ngày không dedup lẫn nhau.
            dedup_hint=f"personal-{kind}:{chat_id}:{local_date}",
            rationale=_KIND_RATIONALE[kind],
        )
        ok = result.status in _OK_STATUSES
        return {"delivered": ok, "delivery_summary": f"telegram={result.status}"}

    builder = StateGraph(ReportState)
    builder.add_node("perceive", perceive)
    builder.add_node("compose_report", compose_report)
    builder.add_node("deliver", deliver)
    builder.add_edge(START, "perceive")
    builder.add_edge("perceive", "compose_report")
    builder.add_edge("compose_report", "deliver")
    if remember is not None:
        add_remember_node(builder, remember)
    else:
        builder.add_edge("deliver", END)
    return builder.compile(checkpointer=checkpointer, store=store)


def build_briefing_graph(checkpointer=None, **kwargs):
    """Bản tin ngày (cron sáng trong profile)."""
    return _build_push_graph("briefing", checkpointer, **kwargs)


def build_weekly_review_graph(checkpointer=None, **kwargs):
    """Bản nhìn lại tuần (cron Chủ Nhật trong profile)."""
    return _build_push_graph("weekly-review", checkpointer, **kwargs)


#: kind → uniform builder. PackRegistry nạp vào Pack.report_kinds.
REPORT_KINDS = {
    "briefing": build_briefing_graph,
    "weekly-review": build_weekly_review_graph,
}
