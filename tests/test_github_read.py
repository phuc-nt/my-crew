"""GitHub read: raw gh JSON → PullRequest/CiRun + staleness (pure parse)."""

from __future__ import annotations

from datetime import date

from my_crew.tools.github_read import _rollup_state, parse_ci, parse_pr

TODAY = date(2026, 6, 21)


def test_parse_pr_stale():
    raw = {
        "number": 42,
        "title": "Add X",
        "author": {"login": "phuc"},
        "updatedAt": "2026-06-01T10:00:00Z",
        "reviewDecision": "REVIEW_REQUIRED",
        "statusCheckRollup": [{"conclusion": "FAILURE"}],
    }
    pr = parse_pr(raw, today=TODAY, stale_days=7)
    assert pr.number == 42
    assert pr.age_days == 20
    assert pr.stale is True
    assert pr.checks_state == "FAILURE"
    assert pr.author == "phuc"


def test_parse_pr_fresh_not_stale():
    raw = {"number": 1, "title": "y", "updatedAt": "2026-06-20T10:00:00Z"}
    pr = parse_pr(raw, today=TODAY, stale_days=7)
    assert pr.stale is False
    assert pr.age_days == 1


def test_parse_pr_boundary_equals_threshold_not_stale():
    # age == stale_days is NOT stale (strictly greater).
    raw = {"number": 2, "title": "z", "updatedAt": "2026-06-14T00:00:00Z"}
    pr = parse_pr(raw, today=TODAY, stale_days=7)
    assert pr.age_days == 7
    assert pr.stale is False


def test_rollup_state_priority():
    assert _rollup_state([{"conclusion": "SUCCESS"}, {"conclusion": "FAILURE"}]) == "FAILURE"
    assert _rollup_state([{"state": "PENDING"}, {"conclusion": "SUCCESS"}]) == "PENDING"
    assert _rollup_state([{"conclusion": "SUCCESS"}]) == "SUCCESS"
    assert _rollup_state([]) is None
    assert _rollup_state(None) is None


def test_parse_ci():
    run = parse_ci({"workflowName": "build", "status": "completed", "conclusion": "failure"})
    assert run.workflow == "build"
    assert run.conclusion == "failure"


def test_parse_pr_bad_number_tolerant():
    # L1: non-numeric number must not crash (tolerant like other parsers).
    pr = parse_pr({"number": "abc", "title": "t"}, today=TODAY, stale_days=7)
    assert pr.number == 0
