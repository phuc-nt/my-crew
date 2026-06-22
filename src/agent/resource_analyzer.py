"""Resource (capacity) + cost analysis — pure functions over Jira issues.

`build_resource_report` groups open issues by assignee and flags overload RELATIVE
to the team mean (no story points available, so load = open-issue count + overdue
+ blocker pressure). `build_cost_summary` derives the cost snapshot from scalars
the caller reads off the existing `BudgetTracker` + reporting config — so this
module stays pure (no I/O, no `datetime.now`, no budget logic duplicated) and is
unit-testable with fixtures. Mirrors the pure-analyzer style of `okr_analyzer`.
"""

from __future__ import annotations

from datetime import date

from src.tools.jira_read import is_done
from src.tools.models import AssigneeLoad, CostSummary, Issue, ResourceReport


def _is_blocker(issue: Issue, *, needle: str) -> bool:
    """An issue is a blocker if flagged or any label contains the needle (lower)."""
    return issue.flagged or any(needle in label.lower() for label in issue.labels)


def build_resource_report(
    issues: list[Issue],
    *,
    today: date,
    overload_ratio: float,
    blocker_label_substring: str,
) -> ResourceReport:
    """Group OPEN issues by assignee and flag overload relative to the team mean.

    Only not-done issues count as "load". Unassigned open issues are counted
    separately (never as an assignee). `overloaded` = open_count above
    `team_mean × overload_ratio`. Loads are returned most-loaded-first.
    """
    needle = blocker_label_substring.lower()
    open_issues = [i for i in issues if not is_done(i)]

    unassigned_count = 0
    order: list[str] = []
    groups: dict[str, list[Issue]] = {}
    for issue in open_issues:
        name = issue.assignee
        if not name:
            unassigned_count += 1
            continue
        if name not in groups:
            order.append(name)
            groups[name] = []
        groups[name].append(issue)

    counts = {name: len(groups[name]) for name in order}
    team_mean = sum(counts.values()) / len(counts) if counts else 0.0
    threshold = team_mean * overload_ratio

    loads: list[AssigneeLoad] = []
    overloaded_names: list[str] = []
    for name in order:
        group = groups[name]
        open_count = len(group)
        overdue_count = sum(
            1 for i in group if i.due_date and i.due_date < today
        )
        blocker_count = sum(1 for i in group if _is_blocker(i, needle=needle))
        overloaded = team_mean > 0 and open_count > threshold
        if overloaded:
            overloaded_names.append(name)
        loads.append(
            AssigneeLoad(
                assignee=name,
                open_count=open_count,
                overdue_count=overdue_count,
                blocker_count=blocker_count,
                overloaded=overloaded,
            )
        )

    # Lead with the signal: most-loaded first, ties broken by name.
    loads.sort(key=lambda load: (-load.open_count, load.assignee))

    return ResourceReport(
        loads=tuple(loads),
        team_mean=team_mean,
        overloaded=tuple(overloaded_names),
        unassigned_count=unassigned_count,
    )


def build_cost_summary(
    open_issue_count: int,
    *,
    llm_spent: float,
    llm_cap: float,
    warn_ratio: float,
    cost_per_issue: float,
) -> CostSummary:
    """Build the cost snapshot from scalars (LLM budget read by the caller).

    Status mirrors `BudgetTracker.check_allowed` (warn at `warn_ratio`, over at
    1.0) WITHOUT raising. Labor estimate is `open_issue_count × cost_per_issue`;
    `cost_per_issue == 0` ⇒ estimate 0.0 (the render layer treats it as n/a).
    """
    ratio = llm_spent / llm_cap if llm_cap > 0 else 0.0
    status = "over" if ratio >= 1.0 else "warn" if ratio >= warn_ratio else "ok"
    labor = open_issue_count * cost_per_issue
    return CostSummary(
        llm_spent=llm_spent,
        llm_cap=llm_cap,
        llm_ratio=ratio,
        llm_status=status,
        labor_estimate=labor,
        open_issue_count=open_issue_count,
        cost_per_issue=cost_per_issue,
    )
