"""Resource+cost fetch + the weekly-embedded resource section (fault-isolated).

Mirrors `okr_weekly_section`. `build_resource_rollup` is the single fetch+analyze
entry shared by the standalone resource graph and the weekly section; the
`weekly_*` helpers wrap it so a missing project key or a fetch failure never
aborts the weekly report.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from src.tools.models import CostSummary, ResourceReport

logger = logging.getLogger(__name__)

Snapshot = tuple[ResourceReport, CostSummary]


def _today_utc() -> date:
    return datetime.now(UTC).date()


def build_resource_rollup() -> Snapshot:
    """Read open Jira issues + the LLM budget → (ResourceReport, CostSummary).

    Raises if `JIRA_PROJECT_KEY` is unset or a fetch fails — callers that must not
    abort (the weekly report) wrap this in `weekly_resource_section`.
    """
    from src.agent.resource_analyzer import build_cost_summary, build_resource_report
    from src.config.reporting_config import get_reporting_config
    from src.config.settings import get_settings
    from src.llm.budget_tracker import BudgetTracker
    from src.tools import jira_read

    cfg = get_reporting_config()
    if not cfg.jira_project_key:
        raise RuntimeError("JIRA_PROJECT_KEY is not set.")
    settings = get_settings()
    issues = jira_read.get_open_issues()
    resource = build_resource_report(
        issues,
        today=_today_utc(),
        overload_ratio=cfg.resource_overload_ratio,
        blocker_label_substring=cfg.blocker_label_substring,
    )
    open_count = sum(load.open_count for load in resource.loads)
    cost = build_cost_summary(
        open_count,
        llm_spent=BudgetTracker().spent_this_month(),
        llm_cap=settings.monthly_budget_usd,
        warn_ratio=settings.budget_warn_ratio,
        cost_per_issue=cfg.labor_cost_per_issue,
    )
    return resource, cost


def weekly_resource_section(report_date: str) -> str:
    """Resource+cost block for the weekly Confluence detail. Fault-isolated.

    Returns "" when no Jira project is configured. On ANY fetch/analyze failure,
    returns a short note (not the raw exception) instead of raising — the weekly
    report must never fail because the resource section failed.
    """
    from src.config.reporting_config import get_reporting_config
    from src.llm.resource_report_prompt import render_resource_xhtml

    if not get_reporting_config().jira_project_key:
        return ""
    try:
        resource, cost = build_resource_rollup()
    except Exception as exc:  # never abort the weekly report on resource failure
        logger.warning("Weekly resource section skipped (fetch/analyze failed): %s", exc)
        return "<p>Không lấy được dữ liệu resource/cost (xem log để biết chi tiết).</p>"
    return render_resource_xhtml(resource, cost, report_date=report_date)


def weekly_resource_slack_line() -> str:
    """One-line resource+cost summary for the weekly Slack short, or "" when off/failed."""
    from src.config.reporting_config import get_reporting_config

    if not get_reporting_config().jira_project_key:
        return ""
    try:
        resource, cost = build_resource_rollup()
    except Exception as exc:
        logger.warning("Weekly resource Slack line skipped: %s", exc)
        return ""
    n = len(resource.loads)
    over = len(resource.overloaded)
    over_txt = f", {over} quá tải" if over else ""
    return f"\n• Resource: {n} người{over_txt} · LLM {cost.llm_ratio * 100:.0f}% ngân sách"
