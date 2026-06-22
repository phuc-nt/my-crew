"""Prompt for composing the progress report (kept out of graph code).

Provider-agnostic: builds a plain message list for `llm.complete`. Follows the
design guidelines — Vietnamese, lead-with-signal (risks first), actionable,
no raw data dumps.

Output targets Slack **mrkdwn** (NOT GitHub markdown): `*bold*` with single
asterisks, `_italic_`, `•` bullets, no `#` headings and no `**`. The caller
passes the real report date so the model never invents a date placeholder.
"""

from __future__ import annotations

from src.tools.models import Risk

_SYSTEM = (
    "Bạn là một PM/SM giỏi, viết báo cáo tiến độ ngắn gọn, thực dụng, bằng tiếng Việt. "
    "Mở đầu bằng rủi ro quan trọng nhất (lead with the signal), mỗi rủi ro kèm hành động "
    "cần làm (ai/cái gì). Không dump dữ liệu thô. Dựa hoàn toàn vào dữ liệu được cung cấp, "
    "không bịa số liệu. Nếu không có rủi ro, nói rõ tiến độ ổn.\n\n"
    "ĐỊNH DẠNG: chỉ dùng Slack mrkdwn — *đậm* (một dấu sao), _nghiêng_, `code`, và "
    "bullet bằng ký tự •. TUYỆT ĐỐI KHÔNG dùng cú pháp Markdown của GitHub: không có "
    "# hay ## heading, không có ** (hai sao), không có gạch đầu dòng bằng '-'. "
    "Không tự chèn placeholder ngày/giờ (vd $(date) hay [Hôm nay]) — dùng đúng ngày được cung cấp."
)


def _format_risks(risks: list[Risk]) -> str:
    if not risks:
        return "Không phát hiện rủi ro từ dữ liệu Jira/GitHub."
    lines = []
    for r in risks:
        lines.append(
            f"- [{r.severity.upper()}] {r.kind} · {r.subject}: {r.detail} "
            f"→ Gợi ý: {r.suggested_action}"
        )
    return "\n".join(lines)


def build_report_messages(risks: list[Risk], *, report_date: str) -> list[dict[str, str]]:
    """Build the chat messages for the report-composing LLM call (Slack mrkdwn).

    `report_date` is the real date string (e.g. '2026-06-21'); it is embedded so
    the model uses it verbatim instead of inventing a placeholder.
    """
    user = (
        f"Viết báo cáo tiến độ cho team ngày {report_date}, dựa trên các tín hiệu rủi ro sau "
        f"(đã sắp xếp theo mức độ):\n\n{_format_risks(risks)}\n\n"
        "Yêu cầu: ngắn gọn, mở đầu bằng rủi ro nghiêm trọng nhất, mỗi mục có hành động đề xuất. "
        "Tiêu đề báo cáo in đậm bằng *một dấu sao*. Bullet bằng •. "
        "Nhớ: KHÔNG dùng #, ##, ** hay '-'."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]


# --- Slice 2: detail report (Confluence storage format) + derived Slack short ---

_DETAIL_SYSTEM = (
    "Bạn là một PM/SM giỏi, viết báo cáo tiến độ đầy đủ bằng tiếng Việt cho trang Confluence. "
    "Mở đầu bằng rủi ro quan trọng nhất, mỗi rủi ro nêu chi tiết + hành động (ai/cái gì). "
    "Dựa hoàn toàn vào dữ liệu được cung cấp, không bịa số liệu.\n\n"
    "ĐỊNH DẠNG: xuất ra Confluence storage format (XHTML đơn giản). CHỈ dùng các thẻ: "
    "<h2>, <h3>, <p>, <ul>, <li>, <strong>, <em>. KHÔNG markdown, KHÔNG <html>/<body>, "
    "KHÔNG thẻ khác. Không tự chèn placeholder ngày — dùng đúng ngày được cung cấp."
)


def build_detail_messages(
    risks: list[Risk],
    *,
    report_date: str,
    kind: str = "daily",
    sprint_context: str | None = None,
) -> list[dict[str, str]]:
    """Messages for the detail report on a Confluence page (XHTML).

    `kind` is "daily" (standup digest — ngắn, hôm nay) or "weekly" (sprint review
    — đầy đủ, cả sprint). `sprint_context` (weekly only) is a short text block of
    sprint name/dates/issue counts the model should summarize.
    """
    if kind == "weekly":
        framing = (
            "Viết BÁO CÁO SPRINT REVIEW (tổng kết tuần) đầy đủ. Nhấn vào tiến độ cả sprint, "
            "việc đã hoàn thành vs còn lại, và rủi ro tới cuối sprint."
        )
        sprint_block = f"\n\nThông tin sprint:\n{sprint_context}" if sprint_context else ""
    else:
        framing = (
            "Viết DAILY STANDUP DIGEST ngắn gọn cho hôm nay. Tập trung tín hiệu cần chú ý "
            "hôm nay, không dài dòng."
        )
        sprint_block = ""

    user = (
        f"{framing} Ngày {report_date}. Dựa trên các tín hiệu sau (đã sắp xếp theo mức độ):"
        f"\n\n{_format_risks(risks)}{sprint_block}\n\n"
        "Bố cục: <h2> tiêu đề, <p> tóm tắt trạng thái, rồi phần rủi ro (mỗi rủi ro 1 <li> "
        "trong <ul>, nêu chi tiết + <strong>hành động</strong>). Nếu không có rủi ro, nói rõ "
        "tiến độ ổn. Chỉ dùng các thẻ cho phép."
    )
    return [
        {"role": "system", "content": _DETAIL_SYSTEM},
        {"role": "user", "content": user},
    ]


# Human-facing titles per report kind (used for the Confluence page title).
REPORT_TITLES = {
    "daily": "Daily Standup",
    "weekly": "Sprint Review",
    "okr": "OKR Status",
    "resource": "Resource & Cost Status",
}


def build_slack_short(risks: list[Risk], *, report_date: str, detail_url: str | None) -> str:
    """Build the short Slack message (mrkdwn) deterministically — no extra LLM call.

    Summarizes status + risk count and links to the Confluence detail page.
    """
    high = sum(1 for r in risks if r.severity == "high")
    if risks:
        status = f"*⚠️ {len(risks)} rủi ro* ({high} cao) — cần chú ý"
        top = risks[0]
        headline = f"\n• Nổi bật: {top.subject} — {top.detail}"
    else:
        status = "*✅ Tiến độ ổn* — không phát hiện rủi ro"
        headline = ""
    link = (
        f"\n📄 <{detail_url}|Xem báo cáo chi tiết trên Confluence>"
        if detail_url
        else "\n_(không tạo được link Confluence)_"
    )
    return f"*Báo cáo tiến độ — {report_date}*\n{status}{headline}{link}"
