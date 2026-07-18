"""Risk analysis — pure functions over normalized Jira/GitHub data.

No I/O, no datetime.now: `today` is passed in, so detection is deterministic and
unit-testable. Detects the Slice-1 risk kinds (overdue task, stale PR, blocker,
CI failure). Thresholds come from the caller (reporting config), not hardcoded
across the module.
"""

from __future__ import annotations

from datetime import date

from my_crew.tools.jira_read import is_done
from my_crew.tools.models import CiRun, Issue, PullRequest, Risk


def _overdue_risks(issues: list[Issue], *, today: date) -> list[Risk]:
    risks: list[Risk] = []
    for issue in issues:
        if issue.due_date and issue.due_date < today and not is_done(issue):
            overdue_by = (today - issue.due_date).days
            risks.append(
                Risk(
                    kind="overdue_task",
                    severity="high" if overdue_by >= 3 else "medium",
                    subject=issue.key,
                    detail=f"{issue.key} quá hạn {overdue_by} ngày (due {issue.due_date}, "
                    f"status {issue.status}).",
                    suggested_action=f"Ping {issue.assignee or 'assignee'} cập nhật hoặc dời hạn.",
                    refs=(issue.key,),
                )
            )
    return risks


def _blocker_risks(issues: list[Issue], *, blocker_label_substring: str) -> list[Risk]:
    risks: list[Risk] = []
    needle = blocker_label_substring.lower()
    for issue in issues:
        is_blocked = issue.flagged or any(needle in label.lower() for label in issue.labels)
        if is_blocked and not is_done(issue):
            risks.append(
                Risk(
                    kind="blocker",
                    severity="high",
                    subject=issue.key,
                    detail=f"{issue.key} bị blocked (labels={list(issue.labels)}, "
                    f"flagged={issue.flagged}).",
                    suggested_action="Gỡ blocker hoặc leo thang cho người liên quan.",
                    refs=(issue.key,),
                )
            )
    return risks


def _stale_pr_risks(prs: list[PullRequest]) -> list[Risk]:
    risks: list[Risk] = []
    for pr in prs:
        if pr.stale:
            risks.append(
                Risk(
                    kind="stale_pr",
                    severity="medium",
                    subject=f"PR#{pr.number}",
                    detail=f"PR#{pr.number} '{pr.title}' treo {pr.age_days} ngày "
                    f"(review={pr.review_decision or 'n/a'}).",
                    suggested_action=f"Nhắc review hoặc đóng PR#{pr.number} nếu hết giá trị.",
                    refs=(f"PR#{pr.number}",),
                )
            )
    return risks


def _ci_failure_risks(ci: list[CiRun]) -> list[Risk]:
    risks: list[Risk] = []
    for run in ci:
        if run.status == "completed" and run.conclusion == "failure":
            risks.append(
                Risk(
                    kind="ci_failure",
                    severity="medium",
                    subject=run.workflow,
                    detail=f"Workflow '{run.workflow}' fail gần đây.",
                    suggested_action=f"Kiểm tra log CI '{run.workflow}', fix trước khi merge.",
                    refs=(run.workflow,),
                )
            )
    return risks


def analyze(
    issues: list[Issue],
    prs: list[PullRequest],
    ci: list[CiRun],
    *,
    today: date,
    blocker_label_substring: str = "block",
) -> list[Risk]:
    """Run all Slice-1 risk rules. Returns risks sorted high→low severity.

    PR staleness is already computed in `PullRequest.stale` by the GitHub tool
    (it owns the stale-days threshold), so this stays threshold-light.
    """
    risks = (
        _overdue_risks(issues, today=today)
        + _blocker_risks(issues, blocker_label_substring=blocker_label_substring)
        + _stale_pr_risks(prs)
        + _ci_failure_risks(ci)
    )
    severity_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(risks, key=lambda r: severity_order.get(r.severity, 9))
