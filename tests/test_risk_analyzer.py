"""Risk analyzer: each Slice-1 rule, boundaries, empty (deterministic via today)."""

from __future__ import annotations

from datetime import date

from my_crew.agent.risk_analyzer import analyze
from my_crew.tools.models import CiRun, Issue, PullRequest

TODAY = date(2026, 6, 21)


def _issue(key, *, status="In Progress", due=None, labels=(), flagged=False):
    return Issue(key=key, summary="s", status=status, assignee="A", due_date=due,
                 labels=labels, flagged=flagged)


def _pr(num, *, stale, age=10):
    return PullRequest(number=num, title="t", author="a", updated_at=TODAY, review_decision=None,
                       checks_state=None, age_days=age, stale=stale)


def test_overdue_detected():
    risks = analyze([_issue("AB-1", due=date(2026, 6, 15))], [], [], today=TODAY)
    assert any(r.kind == "overdue_task" and r.subject == "AB-1" for r in risks)


def test_overdue_but_done_excluded():
    risks = analyze([_issue("AB-2", status="Done", due=date(2026, 6, 1))], [], [], today=TODAY)
    assert not any(r.kind == "overdue_task" for r in risks)


def test_due_today_not_overdue():
    risks = analyze([_issue("AB-3", due=TODAY)], [], [], today=TODAY)
    assert not any(r.kind == "overdue_task" for r in risks)


def test_blocker_via_label():
    risks = analyze([_issue("AB-4", labels=("blocked-by-x",))], [], [], today=TODAY,
                    blocker_label_substring="block")
    assert any(r.kind == "blocker" for r in risks)


def test_blocker_via_flagged():
    risks = analyze([_issue("AB-5", flagged=True)], [], [], today=TODAY)
    assert any(r.kind == "blocker" for r in risks)


def test_stale_pr_detected():
    risks = analyze([], [_pr(9, stale=True)], [], today=TODAY)
    assert any(r.kind == "stale_pr" for r in risks)


def test_fresh_pr_no_risk():
    risks = analyze([], [_pr(9, stale=False)], [], today=TODAY)
    assert not any(r.kind == "stale_pr" for r in risks)


def test_ci_failure_detected():
    risks = analyze([], [], [CiRun(workflow="ci", status="completed", conclusion="failure")],
                    today=TODAY)
    assert any(r.kind == "ci_failure" for r in risks)


def test_ci_success_no_risk():
    risks = analyze([], [], [CiRun(workflow="ci", status="completed", conclusion="success")],
                    today=TODAY)
    assert not risks


def test_empty_inputs_no_risks():
    assert analyze([], [], [], today=TODAY) == []


def test_sorted_high_first():
    risks = analyze(
        [_issue("AB-6", due=date(2026, 6, 1)), _issue("AB-7", flagged=True)],
        [_pr(1, stale=True)], [], today=TODAY,
    )
    severities = [r.severity for r in risks]
    assert severities == sorted(severities, key={"high": 0, "medium": 1, "low": 2}.get)
