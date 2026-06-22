"""Prompt for composing the progress report (kept out of graph code).

Provider-agnostic: builds a plain message list for `llm.complete`. Follows the
design guidelines — Vietnamese, lead-with-signal (risks first), actionable,
no raw data dumps.

Output targets Slack **mrkdwn** (NOT GitHub markdown): `*bold*` with single
asterisks, `_italic_`, `•` bullets, no `#` headings and no `**`. The caller
passes the real report date so the model never invents a date placeholder.
"""

from __future__ import annotations

from src.llm.audience_external_prompts import DETAIL_EXTERNAL_SYSTEM, REPORT_EXTERNAL_SYSTEM
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


# --- Phase 5: external (stakeholder) audience — business tone, no internal detail ---
# External system-prompt strings live in audience_external_prompts (shared, keeps
# this module under the LOC limit).
_EXTERNAL_SYSTEM = REPORT_EXTERNAL_SYSTEM
_DETAIL_EXTERNAL_SYSTEM = DETAIL_EXTERNAL_SYSTEM


def _summarize_risks(risks: list[Risk]) -> str:
    """Audience-external risk view: counts by severity only — NEVER keys/details."""
    if not risks:
        return "Không có rủi ro đáng kể, tiến độ đang ổn định."
    high = sum(1 for r in risks if r.severity == "high")
    medium = sum(1 for r in risks if r.severity == "medium")
    low = len(risks) - high - medium
    parts = []
    if high:
        parts.append(f"{high} nghiêm trọng")
    if medium:
        parts.append(f"{medium} trung bình")
    if low:
        parts.append(f"{low} mức thấp")
    return f"Tổng {len(risks)} hạng mục cần theo dõi ({', '.join(parts)})."


def build_report_messages(
    risks: list[Risk], *, report_date: str, audience: str = "internal"
) -> list[dict[str, str]]:
    """Build the chat messages for the report-composing LLM call (Slack mrkdwn).

    `report_date` is the real date string (e.g. '2026-06-21'); it is embedded so
    the model uses it verbatim instead of inventing a placeholder. `audience`
    "internal" (default) is the full technical report; "external" is a business
    summary for stakeholders (no issue keys / PR numbers).
    """
    if audience == "external":
        user = (
            f"Viết bản cập nhật tiến độ cho stakeholder ngày {report_date}. "
            f"Tình hình: {_summarize_risks(risks)}\n\n"
            "Yêu cầu: ngắn gọn, giọng business, nêu trạng thái tổng quan + mốc quan trọng. "
            "Tiêu đề in đậm bằng *một dấu sao*. Bullet bằng •. KHÔNG #, ##, ** hay '-'. "
            "KHÔNG nêu mã issue, số PR, hay tên người cụ thể."
        )
        return [
            {"role": "system", "content": _EXTERNAL_SYSTEM},
            {"role": "user", "content": user},
        ]
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
    audience: str = "internal",
) -> list[dict[str, str]]:
    """Messages for the detail report on a Confluence page (XHTML).

    `kind` is "daily" (standup digest — ngắn, hôm nay) or "weekly" (sprint review
    — đầy đủ, cả sprint). `sprint_context` (weekly only) is a short text block of
    sprint name/dates/issue counts the model should summarize. `audience`
    "external" produces a business-tone stakeholder page (no internal detail).
    """
    if audience == "external":
        sprint_block = f"\n\nThông tin sprint:\n{sprint_context}" if sprint_context else ""
        user = (
            f"Viết bản cập nhật tiến độ cho stakeholder, ngày {report_date}. "
            f"Tình hình: {_summarize_risks(risks)}{sprint_block}\n\n"
            "Bố cục: <h2> tiêu đề, <p> tóm tắt trạng thái tổng quan, <ul> các mốc/điểm "
            "chính. Giọng business, KHÔNG mã issue / số PR / tên người. Chỉ dùng thẻ cho phép."
        )
        return [
            {"role": "system", "content": _DETAIL_EXTERNAL_SYSTEM},
            {"role": "user", "content": user},
        ]
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


def build_slack_short(
    risks: list[Risk], *, report_date: str, detail_url: str | None, audience: str = "internal"
) -> str:
    """Build the short Slack message (mrkdwn) deterministically — no extra LLM call.

    Summarizes status + risk count and links to the Confluence detail page. For
    `audience="external"` the per-risk headline (which carries an issue key) is
    dropped — stakeholders get status + counts only.
    """
    high = sum(1 for r in risks if r.severity == "high")
    if risks:
        status = f"*⚠️ {len(risks)} rủi ro* ({high} cao) — cần chú ý"
        if audience == "external":
            headline = ""  # no raw issue key in a stakeholder message
        else:
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
