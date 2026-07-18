"""hr-pack headcount analyzer + presentation (v3 M6 S3).

Pure functions over the generic `Task` records the HR ToolProvider returns:
- `build_headcount` groups people by employment status and by department, with totals.
- `render_headcount_xhtml` renders the Confluence detail table (storage XHTML, same tag
  subset PM uses).
- `build_headcount_slack_short` builds the URL-free Slack short (link injected at deliver).
- `fallback_headcount_narrative` is the deterministic prose used when the LLM narrate fails.

Numbers are computed here deterministically (never by the LLM — the Phase-1 lesson): the
LLM only writes the qualitative narrative; every count comes from these functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

from my_crew.tools.models import Task


@dataclass(frozen=True)
class HeadcountGroup:
    """One group (a status or a department) and its member count."""

    dimension: str  # "status" | "department"
    label: str
    count: int


@dataclass(frozen=True)
class HeadcountReport:
    """Team headcount snapshot: total + per-status + per-department breakdowns."""

    total: int
    by_status: tuple[HeadcountGroup, ...]
    by_department: tuple[HeadcountGroup, ...]
    groups: tuple[HeadcountGroup, ...] = field(default_factory=tuple)  # status+dept, for state


def build_headcount(tasks: list[Task]) -> HeadcountReport:
    """Count people (one Task = one person) grouped by status and by department.

    A person's department is the first label (the ToolProvider puts dept first); status
    is `Task.status`. Missing values fall into "unknown" / "unspecified" buckets rather
    than being dropped, so the totals always reconcile.
    """
    status_counts: dict[str, int] = {}
    dept_counts: dict[str, int] = {}
    for t in tasks:
        status = (t.status or "unknown").strip() or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        dept = t.labels[0].strip() if t.labels and t.labels[0].strip() else "unspecified"
        dept_counts[dept] = dept_counts.get(dept, 0) + 1

    by_status = tuple(
        HeadcountGroup("status", k, v)
        for k, v in sorted(status_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    by_department = tuple(
        HeadcountGroup("department", k, v)
        for k, v in sorted(dept_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    return HeadcountReport(
        total=len(tasks),
        by_status=by_status,
        by_department=by_department,
        groups=by_status + by_department,
    )


def render_headcount_xhtml(report: HeadcountReport, report_date: str) -> str:
    """Render the Confluence detail body (storage XHTML) — deterministic, no LLM."""
    parts = [f"<h2>Báo cáo nhân sự (Headcount) — {escape(report_date)}</h2>"]
    parts.append(f"<p>Tổng số nhân sự: <strong>{report.total}</strong></p>")
    parts.append(_group_table("Theo trạng thái", report.by_status))
    parts.append(_group_table("Theo phòng ban", report.by_department))
    return "".join(parts)


def _group_table(heading: str, groups: tuple[HeadcountGroup, ...]) -> str:
    if not groups:
        return f"<h3>{escape(heading)}</h3><p>Không có dữ liệu.</p>"
    rows = "".join(
        f"<tr><td>{escape(g.label)}</td><td>{g.count}</td></tr>" for g in groups
    )
    return (
        f"<h3>{escape(heading)}</h3>"
        f"<table><tbody><tr><th>Nhóm</th><th>Số lượng</th></tr>{rows}</tbody></table>"
    )


def build_headcount_slack_short(
    report: HeadcountReport, *, report_date: str, audience: str = "internal"
) -> str:
    """URL-free Slack short (mrkdwn). The Confluence link is injected at deliver (and
    withheld for the external audience). Both audiences see only aggregate counts —
    headcount never exposes individual names — so the external short is a coarser
    summary (total + top status), no per-department drill-down."""
    top_status = report.by_status[0] if report.by_status else None
    lines = [f"*Báo cáo nhân sự — {report_date}*", f"Tổng: *{report.total}* nhân sự"]
    if top_status:
        lines.append(f"• Trạng thái nhiều nhất: {top_status.label} ({top_status.count})")
    if audience != "external":
        top_dept = report.by_department[0] if report.by_department else None
        if top_dept:
            lines.append(f"• Phòng ban đông nhất: {top_dept.label} ({top_dept.count})")
    return "\n".join(lines)


def fallback_headcount_narrative(report: HeadcountReport) -> str:
    """Deterministic prose used when the LLM narrate call fails — never blocks delivery."""
    return (
        f"<p>Tổng quan nhân sự: <strong>{report.total}</strong> người, "
        f"phân theo {len(report.by_status)} trạng thái và "
        f"{len(report.by_department)} phòng ban.</p>"
    )
