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
from src.llm.report_slack_short import REPORT_TITLES, build_slack_short
from src.packs.registry import load_pack_prompt
from src.profile.context import build_context_block, prepend_persona
from src.tools.models import Risk

# `build_slack_short` + REPORT_TITLES (re-exported above) are deterministic (no
# persona/LLM), so they live in `report_slack_short`; importers still use
# `from src.llm.report_prompt import ...` — a stable public path.

# v3 M5 S5: the PM system-prompt text is a pm-pack asset
# (`domain-packs/pm-pack/prompts/report-system.md`), read verbatim so the composed
# prompt is byte-identical to the pre-v3 literal. The builder logic stays here in core.
_SYSTEM = load_pack_prompt("pm", "report-system")


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


def _text_block(text: str) -> str:
    """Trailing block (skill bodies or sibling facts) prepended to the INTERNAL user
    message after project/memory. Empty ⇒ "" so a no-injection run is byte-identical."""
    text = text.strip()
    return f"{text}\n\n" if text else ""


def build_report_messages(
    risks: list[Risk],
    *,
    report_date: str,
    audience: str = "internal",
    persona: str = "",
    project: str = "",
    memory: str = "",
    skills: str = "",
    company_docs: str = "",
    sibling_facts: str = "",
) -> list[dict[str, str]]:
    """Build the chat messages for the report-composing LLM call (Slack mrkdwn).

    `report_date` is the real date string (e.g. '2026-06-21'); it is embedded so
    the model uses it verbatim instead of inventing a placeholder. `audience`
    "internal" (default) is the full technical report; "external" is a business
    summary for stakeholders (no issue keys / PR numbers). `persona` prepends to the
    system message; `project`/`memory`/`skills`/`company_docs`/`sibling_facts` prepend to
    the INTERNAL user message only (never external — they carry internal facts). All ""
    ⇒ v1 prompt.
    """
    if audience == "external":
        user = (
            f"Viết bản cập nhật tiến độ cho stakeholder ngày {report_date}. "
            f"Tình hình: {_summarize_risks(risks)}\n\n"
            "Yêu cầu: ngắn gọn, giọng business, nêu trạng thái tổng quan + mốc quan trọng. "
            "Tiêu đề in đậm bằng *một dấu sao*. Bullet bằng •. KHÔNG #, ##, ** hay '-'. "
            "KHÔNG nêu mã issue, số PR, hay tên người cụ thể."
        )
        # External path takes NOTHING from the profile: no persona (a hostile SOUL.md
        # could otherwise sit above the "no keys/names" rule in the same system
        # message), no project/memory (internal facts). The external system prompt is
        # the sole authority for a stakeholder report. (Phase-5 PII guardrail.)
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
        {"role": "system", "content": prepend_persona(_SYSTEM, persona)},
        {
            "role": "user",
            "content": build_context_block(project, memory)
            + _text_block(skills) + _text_block(company_docs)
            + _text_block(sibling_facts) + user,
        },
    ]


# --- Slice 2: detail report (Confluence storage format) + derived Slack short ---

_DETAIL_SYSTEM = load_pack_prompt("pm", "report-detail-system")


def build_detail_messages(
    risks: list[Risk],
    *,
    report_date: str,
    kind: str = "daily",
    sprint_context: str | None = None,
    audience: str = "internal",
    persona: str = "",
    project: str = "",
    memory: str = "",
    skills: str = "",
    company_docs: str = "",
    sibling_facts: str = "",
) -> list[dict[str, str]]:
    """Messages for the detail report on a Confluence page (XHTML).

    `kind` is "daily" (standup digest — ngắn, hôm nay) or "weekly" (sprint review
    — đầy đủ, cả sprint). `sprint_context` (weekly only) is a short text block of
    sprint name/dates/issue counts the model should summarize. `audience`
    "external" produces a business-tone stakeholder page (no internal detail).
    `persona`/`project`/`memory`/`skills`/`sibling_facts` inject as in
    `build_report_messages` (all internal-only). All default "" ⇒ v1 prompt.
    """
    if audience == "external":
        sprint_block = f"\n\nThông tin sprint:\n{sprint_context}" if sprint_context else ""
        user = (
            f"Viết bản cập nhật tiến độ cho stakeholder, ngày {report_date}. "
            f"Tình hình: {_summarize_risks(risks)}{sprint_block}\n\n"
            "Bố cục: <h2> tiêu đề, <p> tóm tắt trạng thái tổng quan, <ul> các mốc/điểm "
            "chính. Giọng business, KHÔNG mã issue / số PR / tên người. Chỉ dùng thẻ cho phép."
        )
        # External path takes NOTHING from the profile (see build_report_messages).
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
        {"role": "system", "content": prepend_persona(_DETAIL_SYSTEM, persona)},
        {
            "role": "user",
            "content": build_context_block(project, memory)
            + _text_block(skills) + _text_block(company_docs)
            + _text_block(sibling_facts) + user,
        },
    ]


__all__ = [
    "REPORT_TITLES",
    "build_detail_messages",
    "build_report_messages",
    "build_slack_short",
]
