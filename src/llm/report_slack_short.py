"""Deterministic Slack short message + report titles (no LLM call).

Split out of `report_prompt.py` to keep that file under the 200-LOC gate. The Slack
short is built deterministically from the risk list (status + count + a link to the
Confluence detail page) — it takes no persona/project/memory, so it lives apart from
the LLM message builders. `report_prompt` re-exports these so the public import path
(`from src.llm.report_prompt import REPORT_TITLES, build_slack_short`) is unchanged.
"""

from __future__ import annotations

from src.tools.models import Risk

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
