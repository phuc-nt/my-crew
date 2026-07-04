"""OKR report rendering — deterministic XHTML/Slack + optional LLM narrative.

The OKR numbers (progress %, weights, counts) are rendered HERE from the computed
`OkrRollup`, never by the LLM — so the figures can't be hallucinated. The LLM (if
available) only writes a short Vietnamese narrative paragraph placed ABOVE the
deterministic table; without a key the compose step falls back to a templated
summary line (see `okr_report_graph`).

Confluence storage XHTML uses the same whitelisted tags as the detail report plus
``<table>/<tr>/<th>/<td>`` (verified to round-trip through createPage 2026-06-22).
Slack output is mrkdwn (single ``*``, ``•`` bullets — no ``#``/``**``/``-``).
"""

from __future__ import annotations

from html import escape

from src.agent.okr_analyzer import OkrRollup
from src.llm.audience_external_prompts import OKR_NARRATIVE_EXTERNAL_SYSTEM
from src.llm.slack_link import slack_link_line
from src.packs.registry import load_pack_prompt
from src.profile.context import build_context_block, prepend_persona


def _fmt_pct(value: float | None) -> str:
    """Render a 0..100 progress value for display, or a dash when unknown."""
    return f"{value:.0f}%" if value is not None else "—"


def _fmt_weight(value: float | None) -> str:
    return f"{value:g}" if value is not None else "—"


def render_okr_table_xhtml(rollup: OkrRollup, *, report_date: str) -> str:
    """Build the Confluence storage body for the OKR status (deterministic).

    Layout: an <h2> title, a <table> of Objective/KR/progress/weight, a <ul> of
    at-risk objectives, and a "OKR có vấn đề" <ul> of problems. All numbers come
    from `rollup`, escaped for XHTML.
    """
    parts: list[str] = [f"<h2>OKR Status — {escape(report_date)}</h2>"]

    if rollup.objectives:
        rows = [
            "<tr><th>Objective</th><th>Tiến độ</th><th>Key Result</th>"
            "<th>Tiến độ KR</th><th>Trọng số</th></tr>"
        ]
        for obj in rollup.objectives:
            krs = obj.key_results or ()
            span = len(krs) or 1
            for i, kr in enumerate(krs):
                cells = ""
                if i == 0:
                    cells = (
                        f'<td rowspan="{span}"><strong>{escape(obj.name)}</strong></td>'
                        f'<td rowspan="{span}">{_fmt_pct(obj.progress_pct)}</td>'
                    )
                rows.append(
                    f"<tr>{cells}<td>{escape(kr.description)}</td>"
                    f"<td>{_fmt_pct(kr.progress_pct)}</td>"
                    f"<td>{_fmt_weight(kr.weight)}</td></tr>"
                )
            if not krs:  # objective with no usable KRs (all problems)
                rows.append(
                    f"<tr><td><strong>{escape(obj.name)}</strong></td>"
                    f"<td>{_fmt_pct(obj.progress_pct)}</td><td>—</td><td>—</td><td>—</td></tr>"
                )
        parts.append("<table><tbody>" + "".join(rows) + "</tbody></table>")
    else:
        parts.append("<p>Chưa có Objective hợp lệ nào trong bảng OKR.</p>")

    if rollup.at_risk:
        items = "".join(f"<li>{escape(name)}</li>" for name in rollup.at_risk)
        parts.append(f"<h3>Objective cần chú ý (dưới ngưỡng)</h3><ul>{items}</ul>")

    if rollup.problems:
        items = "".join(
            f"<li>{escape(p.row)} — {escape(p.reason)}</li>" for p in rollup.problems
        )
        parts.append(f"<h3>OKR có vấn đề</h3><ul>{items}</ul>")

    return "".join(parts)


def overall_pct(rollup: OkrRollup) -> float | None:
    """Simple mean of objective progresses (for the headline line)."""
    vals = [o.progress_pct for o in rollup.objectives if o.progress_pct is not None]
    return sum(vals) / len(vals) if vals else None


def build_okr_slack_short(
    rollup: OkrRollup, *, report_date: str, detail_url: str | None, audience: str = "internal"
) -> str:
    """Deterministic Slack mrkdwn summary of the OKR status (no LLM).

    Objective names are business-level (not issue keys), so the external variant
    keeps the progress + at-risk objectives but drops the internal "OKR có vấn đề"
    data-quality line (internal noise).
    """
    n = len(rollup.objectives)
    overall = overall_pct(rollup)
    overall_txt = f"{overall:.0f}%" if overall is not None else "n/a"
    head = f"*OKR Status — {report_date}*\n*{n} objective · trung bình {overall_txt}*"

    if rollup.at_risk:
        risks = ", ".join(rollup.at_risk)
        head += f"\n• ⚠️ Cần chú ý: {risks}"
    if rollup.problems and audience != "external":
        head += f"\n• {len(rollup.problems)} dòng OKR có vấn đề"

    return head + slack_link_line(detail_url, text="Xem OKR chi tiết trên Confluence")


_NARRATIVE_SYSTEM = load_pack_prompt("pm", "okr-narrative-system")

def build_okr_narrative_messages(
    rollup: OkrRollup,
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
    """Messages for the 1-paragraph LLM narrative placed above the OKR table.

    The model is told the qualitative situation (counts + which objectives are at
    risk), NOT asked to compute or restate percentages — the table owns the numbers.
    `audience="external"` swaps to a business-tone system prompt (objective names
    are business-level, so they may appear). `persona`/`project`/`memory`/`skills`/
    `sibling_facts` inject as in `build_report_messages` (all internal-only); default
    "" ⇒ v1.
    """
    at_risk = ", ".join(rollup.at_risk) if rollup.at_risk else "không có"
    problem_count = len(rollup.problems)
    summary = (
        f"Ngày {report_date}. Số objective: {len(rollup.objectives)}. "
        f"Objective cần chú ý: {at_risk}. Số dòng OKR có vấn đề: {problem_count}."
    )
    user = (
        f"Dữ liệu tình hình OKR (định tính):\n{summary}\n\n"
        "Viết một đoạn <p> tóm tắt ngắn gọn cho lãnh đạo: tổng quan tiến độ, nhấn vào "
        "objective cần chú ý nếu có, giọng thực dụng. Nhớ: KHÔNG nêu số phần trăm cụ thể."
    )
    if audience == "external":
        # External path takes NOTHING from the profile (Phase-5 PII guardrail): no
        # persona, no project/memory — the external system prompt is the sole authority.
        return [
            {"role": "system", "content": OKR_NARRATIVE_EXTERNAL_SYSTEM},
            {"role": "user", "content": user},
        ]
    skill_block = f"{skills.strip()}\n\n" if skills.strip() else ""
    docs_block = f"{company_docs.strip()}\n\n" if company_docs.strip() else ""
    sibling_block = f"{sibling_facts.strip()}\n\n" if sibling_facts.strip() else ""
    return [
        {"role": "system", "content": prepend_persona(_NARRATIVE_SYSTEM, persona)},
        {"role": "user",
         "content": build_context_block(project, memory)
         + skill_block + docs_block + sibling_block + user},
    ]


def fallback_okr_narrative(
    rollup: OkrRollup, *, report_date: str, audience: str = "internal"
) -> str:
    """Templated <p> summary used when no LLM is available (no key).

    `audience` does not change this template (it carries only objective names +
    counts, all business-safe); the param keeps the call sites uniform.
    """
    if rollup.at_risk:
        focus = "Cần chú ý: " + ", ".join(rollup.at_risk) + "."
    else:
        focus = "Không có objective nào dưới ngưỡng."
    problems = (
        f" {len(rollup.problems)} dòng OKR có vấn đề cần rà soát." if rollup.problems else ""
    )
    return (
        f"<p>Cập nhật OKR ngày {escape(report_date)}: {len(rollup.objectives)} objective. "
        f"{escape(focus)}{escape(problems)}</p>"
    )
