"""Slice A: resource + cost analyzer — pure (team-mean overload, cost bands)."""

from __future__ import annotations

from datetime import date

import pytest

from src.agent.resource_analyzer import build_cost_summary, build_resource_report
from src.llm.budget_tracker import BudgetTracker
from src.tools.models import Issue

TODAY = date(2026, 6, 22)


def _issue(key, assignee, *, status="To Do", due=None, labels=(), flagged=False):
    return Issue(
        key=key, summary="", status=status, assignee=assignee,
        due_date=due, labels=tuple(labels), flagged=flagged,
    )


def _report(issues, *, ratio=1.5):
    return build_resource_report(
        issues, today=TODAY, overload_ratio=ratio, blocker_label_substring="block"
    )


# --- team mean + relative overload ---


def test_team_mean_and_overload():
    # open counts 1, 2, 6 → mean 3.0; threshold 3.0×1.5 = 4.5 → only the 6 is over.
    issues = (
        [_issue("A-1", "Alice")]
        + [_issue(f"B-{i}", "Bob") for i in range(2)]
        + [_issue(f"C-{i}", "Carol") for i in range(6)]
    )
    rep = _report(issues)
    assert rep.team_mean == pytest.approx(3.0)
    assert rep.overloaded == ("Carol",)
    by = {load.assignee: load for load in rep.loads}
    assert by["Carol"].overloaded is True
    assert by["Alice"].overloaded is False and by["Bob"].overloaded is False


def test_overdue_and_blocker_counts():
    issues = [
        _issue("X-1", "Dan", due=date(2026, 6, 10)),         # overdue
        _issue("X-2", "Dan", labels=["Blocked"]),            # blocker via label (case-insens)
        _issue("X-3", "Dan", flagged=True),                  # blocker via flag
        _issue("X-4", "Dan"),                                # plain
    ]
    load = _report(issues).loads[0]
    assert load.assignee == "Dan"
    assert load.open_count == 4
    assert load.overdue_count == 1
    assert load.blocker_count == 2  # label + flagged


def test_done_issues_excluded():
    issues = [
        _issue("D-1", "Eve", status="Done"),   # done → not load
        _issue("D-2", "Eve"),
    ]
    rep = _report(issues)
    assert rep.loads[0].open_count == 1


def test_unassigned_separated():
    issues = [
        _issue("U-1", None),
        _issue("U-2", ""),
        _issue("U-3", "Frank"),
    ]
    rep = _report(issues)
    assert rep.unassigned_count == 2
    assert [load.assignee for load in rep.loads] == ["Frank"]
    assert rep.team_mean == pytest.approx(1.0)  # unassigned don't affect the mean


# --- degenerate cases ---


def test_empty_issues():
    rep = _report([])
    assert rep.loads == () and rep.team_mean == 0.0
    assert rep.overloaded == () and rep.unassigned_count == 0


def test_single_assignee_never_self_overloaded():
    rep = _report([_issue(f"S-{i}", "Solo") for i in range(10)])
    assert rep.team_mean == pytest.approx(10.0)
    # threshold = 10 × 1.5 = 15 > 10 → not overloaded
    assert rep.overloaded == ()
    assert rep.loads[0].overloaded is False


def test_all_unassigned():
    rep = _report([_issue("N-1", None), _issue("N-2", None)])
    assert rep.loads == () and rep.team_mean == 0.0 and rep.unassigned_count == 2


def test_loads_sorted_most_loaded_first():
    issues = (
        [_issue("a", "Low")]
        + [_issue(f"b{i}", "High") for i in range(5)]
        + [_issue(f"c{i}", "Mid") for i in range(3)]
    )
    rep = _report(issues)
    assert [load.assignee for load in rep.loads] == ["High", "Mid", "Low"]


# --- cost summary ---


def test_cost_status_bands():
    ok = build_cost_summary(0, llm_spent=10, llm_cap=50, warn_ratio=0.8, cost_per_issue=0)
    assert ok.llm_ratio == pytest.approx(0.2) and ok.llm_status == "ok"
    warn = build_cost_summary(0, llm_spent=45, llm_cap=50, warn_ratio=0.8, cost_per_issue=0)
    assert warn.llm_status == "warn"  # 0.9 ≥ 0.8
    over = build_cost_summary(0, llm_spent=50, llm_cap=50, warn_ratio=0.8, cost_per_issue=0)
    assert over.llm_status == "over"  # 1.0 ≥ 1.0


def test_cost_zero_cap_is_ok():
    s = build_cost_summary(0, llm_spent=5, llm_cap=0, warn_ratio=0.8, cost_per_issue=0)
    assert s.llm_ratio == 0.0 and s.llm_status == "ok"


def test_labor_estimate():
    s = build_cost_summary(8, llm_spent=0, llm_cap=50, warn_ratio=0.8, cost_per_issue=25)
    assert s.labor_estimate == pytest.approx(200.0)
    zero = build_cost_summary(8, llm_spent=0, llm_cap=50, warn_ratio=0.8, cost_per_issue=0)
    assert zero.labor_estimate == 0.0


def test_cost_summary_reads_real_tracker(settings_factory):
    # Confirms the real budget read path lines up with the pure function.
    bt = BudgetTracker(settings_factory(monthly_budget_usd=50.0, budget_warn_ratio=0.8))
    bt.record_cost(45.0)  # 90% → warn
    s = build_cost_summary(
        10, llm_spent=bt.spent_this_month(), llm_cap=50.0, warn_ratio=0.8, cost_per_issue=0
    )
    assert s.llm_spent == pytest.approx(45.0) and s.llm_status == "warn"
