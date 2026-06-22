"""Resource + cost report rendering — deterministic XHTML/Slack + LLM narrative.

All numbers (per-assignee counts, team mean, $, %) are rendered HERE from the
computed `ResourceReport`/`CostSummary`, never by the LLM — so figures can't be
hallucinated. The LLM (if available) writes only a short Vietnamese narrative
paragraph above the deterministic tables.

Assignee names come from Jira (user-controlled display strings) and flow into
Confluence XHTML — every one is `html.escape`d before rendering. Slack output is
mrkdwn (single ``*``, ``•`` — no ``#``/``**``/``-``).
"""

from __future__ import annotations

from html import escape

from src.tools.models import CostSummary, ResourceReport

_STATUS_WORD = {"ok": "trong ngưỡng", "warn": "⚠️ gần ngưỡng", "over": "❌ vượt ngưỡng"}

# Slack mrkdwn has no HTML escaping; assignee names are Jira user-controlled
# display strings, so neutralize the active mrkdwn / link / mention control chars
# before interpolating a name into a Slack message (a name like "<!channel>" or
# "<https://x|y>" or "*foo*" would otherwise inject a mention/link or break format).
_SLACK_UNSAFE = str.maketrans(
    {"*": "·", "_": " ", "<": "‹", ">": "›", "`": "'", "~": "-", "@": "(at)", "&": "+"}
)


def _slack_safe(name: str) -> str:
    """Make a user-controlled name safe to interpolate into Slack mrkdwn."""
    return name.translate(_SLACK_UNSAFE)


def _fmt_money(value: float) -> str:
    """Render a USD amount, e.g. 1234.5 → '$1,234'."""
    return f"${value:,.0f}"


def _fmt_pct(ratio: float) -> str:
    """Render a 0..1 ratio as a whole percent."""
    return f"{ratio * 100:.0f}%"


def _cost_lines(cost: CostSummary) -> list[str]:
    """The LLM-budget li + optional labor-estimate li (shared XHTML/text source)."""
    status = _STATUS_WORD.get(cost.llm_status, cost.llm_status)
    lines = [
        f"LLM tháng này: {_fmt_money(cost.llm_spent)} / {_fmt_money(cost.llm_cap)} "
        f"({_fmt_pct(cost.llm_ratio)}) — {status}"
    ]
    if cost.cost_per_issue > 0:
        lines.append(
            f"Ước tính nhân công (tham khảo): {_fmt_money(cost.labor_estimate)} "
            f"({cost.open_issue_count} issue × {_fmt_money(cost.cost_per_issue)})"
        )
    return lines


def render_resource_xhtml(
    resource: ResourceReport, cost: CostSummary, *, report_date: str
) -> str:
    """Build the Confluence storage body for the resource + cost status."""
    parts: list[str] = [f"<h2>Resource &amp; Cost Status — {escape(report_date)}</h2>"]

    if resource.loads:
        rows = [
            "<tr><th>Người</th><th>Mở</th><th>Quá hạn</th><th>Blocker</th><th>Tải</th></tr>"
        ]
        for load in resource.loads:
            tag = "⚠️ quá tải" if load.overloaded else "ok"
            rows.append(
                f"<tr><td>{escape(load.assignee)}</td><td>{load.open_count}</td>"
                f"<td>{load.overdue_count}</td><td>{load.blocker_count}</td>"
                f"<td>{tag}</td></tr>"
            )
        parts.append("<table><tbody>" + "".join(rows) + "</tbody></table>")
        parts.append(f"<p>Tải trung bình team: {resource.team_mean:.1f} issue/người.</p>")
    else:
        parts.append("<p>Chưa có issue nào được phân công.</p>")

    if resource.unassigned_count > 0:
        parts.append(f"<p>Chưa phân công: {resource.unassigned_count} issue.</p>")

    cost_items = "".join(f"<li>{escape(line)}</li>" for line in _cost_lines(cost))
    parts.append(f"<h3>Chi phí</h3><ul>{cost_items}</ul>")

    return "".join(parts)


def build_resource_slack_short(
    resource: ResourceReport, cost: CostSummary, *, report_date: str, detail_url: str | None
) -> str:
    """Deterministic Slack mrkdwn summary of the resource + cost status (no LLM)."""
    open_total = sum(load.open_count for load in resource.loads)
    head = (
        f"*Resource & Cost — {report_date}*\n"
        f"*{len(resource.loads)} người · {open_total} issue đang mở*"
    )
    if resource.overloaded:
        names = ", ".join(_slack_safe(n) for n in resource.overloaded)
        head += f"\n• ⚠️ Quá tải: {names}"
    if resource.unassigned_count > 0:
        head += f"\n• Chưa phân công: {resource.unassigned_count} issue"

    status = _STATUS_WORD.get(cost.llm_status, cost.llm_status)
    head += (
        f"\n• LLM: {_fmt_money(cost.llm_spent)}/{_fmt_money(cost.llm_cap)} "
        f"({_fmt_pct(cost.llm_ratio)}) — {status}"
    )
    if cost.cost_per_issue > 0:
        head += f"\n• Nhân công (ước tính): {_fmt_money(cost.labor_estimate)}"

    link = (
        f"\n📄 <{detail_url}|Xem chi tiết trên Confluence>"
        if detail_url
        else "\n_(không tạo được link Confluence)_"
    )
    return head + link


_NARRATIVE_SYSTEM = (
    "Bạn là một PM/SM giỏi, viết MỘT đoạn tóm tắt ngắn (2-4 câu) bằng tiếng Việt về tình hình "
    "tải công việc và chi phí của team. KHÔNG nhắc lại con số cụ thể (bảng số liệu đã có riêng) "
    "— chỉ nêu định tính: ai đang quá tải, ngân sách có gần ngưỡng không, đề xuất cân bằng nếu "
    "cần. ĐỊNH DẠNG: chỉ một thẻ <p> (Confluence storage XHTML), có thể dùng <strong>/<em>. "
    "KHÔNG heading, KHÔNG markdown, KHÔNG bịa thông tin ngoài dữ liệu được cung cấp."
)


def build_resource_narrative_messages(
    resource: ResourceReport, cost: CostSummary, *, report_date: str
) -> list[dict[str, str]]:
    """Messages for the 1-paragraph LLM narrative placed above the tables.

    Passes qualitative facts only (who is overloaded, budget status word), never
    raw figures — the tables own the numbers.
    """
    overloaded = (
        ", ".join(_slack_safe(n) for n in resource.overloaded)
        if resource.overloaded
        else "không có"
    )
    budget_word = _STATUS_WORD.get(cost.llm_status, cost.llm_status)
    summary = (
        f"Ngày {report_date}. Số người có việc: {len(resource.loads)}. "
        f"Người quá tải: {overloaded}. Chưa phân công: {resource.unassigned_count} issue. "
        f"Ngân sách LLM: {budget_word}."
    )
    user = (
        f"Dữ liệu tình hình resource & cost (định tính):\n{summary}\n\n"
        "Viết một đoạn <p> tóm tắt ngắn cho lãnh đạo: tổng quan tải team, nhấn vào người "
        "quá tải và tình trạng ngân sách nếu đáng chú ý. Nhớ: KHÔNG nêu số cụ thể."
    )
    return [
        {"role": "system", "content": _NARRATIVE_SYSTEM},
        {"role": "user", "content": user},
    ]


def fallback_resource_narrative(
    resource: ResourceReport, cost: CostSummary, *, report_date: str
) -> str:
    """Templated <p> summary used when no LLM is available (no key)."""
    if resource.overloaded:
        focus = "Cần cân bằng tải: " + ", ".join(resource.overloaded) + " đang quá tải."
    else:
        focus = "Tải công việc phân bố đều, không ai quá tải."
    budget = ""
    if cost.llm_status != "ok":
        budget = f" Ngân sách LLM {_STATUS_WORD.get(cost.llm_status, cost.llm_status)}."
    return (
        f"<p>Cập nhật resource &amp; cost ngày {escape(report_date)}: "
        f"{len(resource.loads)} người có việc. {escape(focus)}{escape(budget)}</p>"
    )
