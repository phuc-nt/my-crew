"""Slice B: OKR analyzer — weighted rollup, fallbacks, problems, at-risk (pure)."""

from __future__ import annotations

import pytest

from my_crew.agent.okr_analyzer import build_objectives
from my_crew.tools.models import EpicProgress


def _ep(key: str, done: int, total: int) -> EpicProgress:
    pct = 100.0 * done / total if total else None
    return EpicProgress(key, pct, done, total, found=total > 0)


def test_equal_weighting_blank_weights():
    rows = [
        ("O1", "KR1", "EA-1", ""),
        ("O1", "KR2", "EB-1", ""),
    ]
    progress = {"EA-1": _ep("EA-1", 8, 10), "EB-1": _ep("EB-1", 4, 10)}  # 80% + 40%
    rollup = build_objectives(rows, progress, behind_threshold=0.5)
    assert rollup.problems == ()
    assert len(rollup.objectives) == 1
    assert rollup.objectives[0].progress_pct == pytest.approx(60.0)


def test_explicit_weights():
    rows = [
        ("O1", "KR1", "EA-1", "0.75"),
        ("O1", "KR2", "EB-1", "0.25"),
    ]
    progress = {"EA-1": _ep("EA-1", 8, 10), "EB-1": _ep("EB-1", 4, 10)}  # 80% , 40%
    rollup = build_objectives(rows, progress, behind_threshold=0.5)
    # 80*0.75 + 40*0.25 = 70
    assert rollup.objectives[0].progress_pct == pytest.approx(70.0)


def test_mixed_blank_weight_forces_equal_weighting():
    rows = [
        ("O1", "KR1", "EA-1", "0.9"),  # explicit
        ("O1", "KR2", "EB-1", ""),     # blank -> whole objective equal-weighted
    ]
    progress = {"EA-1": _ep("EA-1", 8, 10), "EB-1": _ep("EB-1", 4, 10)}  # 80, 40
    rollup = build_objectives(rows, progress, behind_threshold=0.5)
    assert rollup.objectives[0].progress_pct == pytest.approx(60.0)  # equal, not weighted


def test_multi_epic_kr_child_count_weighting():
    # epicA 1/1 done (100%), epicB 0/49 (0%) -> KR ≈ 2% (1/50), NOT 50%.
    rows = [("O1", "KR1", "EA-1 EB-1", "")]
    progress = {"EA-1": _ep("EA-1", 1, 1), "EB-1": _ep("EB-1", 0, 49)}
    rollup = build_objectives(rows, progress, behind_threshold=0.5)
    assert rollup.objectives[0].progress_pct == pytest.approx(2.0)


def test_multi_epic_fallback_to_mean_when_counts_missing():
    rows = [("O1", "KR1", "EA-1 EB-1", "")]
    # EB-1 has a percent but no usable counts (total 0 but progress given) -> mean.
    progress = {
        "EA-1": _ep("EA-1", 6, 10),  # 60%
        "EB-1": EpicProgress("EB-1", 20.0, None, None, found=True),  # 20%, no counts
    }
    rollup = build_objectives(rows, progress, behind_threshold=0.5)
    assert rollup.objectives[0].progress_pct == pytest.approx(40.0)  # mean(60,20)


def test_malformed_weight_is_a_problem_others_still_roll_up():
    rows = [
        ("O1", "KR1", "EA-1", "oops"),  # bad weight -> problem, skip
        ("O1", "KR2", "EB-1", "0.5"),
    ]
    progress = {"EA-1": _ep("EA-1", 5, 10), "EB-1": _ep("EB-1", 6, 10)}
    rollup = build_objectives(rows, progress, behind_threshold=0.5)
    assert len(rollup.problems) == 1
    assert "weight" in rollup.problems[0].reason
    assert rollup.objectives[0].progress_pct == pytest.approx(60.0)  # only KR2


def test_missing_epic_key_is_a_problem():
    # A row with no epic key is structurally invalid: it yields a problem and no
    # KR, so an Objective whose only row is bad never materializes (it lives in
    # problems, not objectives). Contrast test_unknown_epic_excluded_and_reported,
    # where the row is valid but the epic doesn't resolve.
    rows = [("O1", "KR1", "", "")]
    rollup = build_objectives(rows, {}, behind_threshold=0.5)
    assert any("Epic Key" in p.reason for p in rollup.problems)
    assert rollup.objectives == ()


def test_unknown_epic_excluded_and_reported():
    rows = [("O1", "KR1", "EGOOD-1 EBAD-1", "")]
    progress = {"EGOOD-1": _ep("EGOOD-1", 5, 10)}  # EBAD-1 absent from map
    rollup = build_objectives(rows, progress, behind_threshold=0.5)
    assert rollup.objectives[0].progress_pct == pytest.approx(50.0)  # rolled over good one
    assert any("EBAD-1" in p.reason for p in rollup.problems)


def test_at_risk_detection():
    rows = [
        ("Behind", "KR1", "EA-1", ""),
        ("OnTrack", "KR2", "EB-1", ""),
    ]
    progress = {"EA-1": _ep("EA-1", 3, 10), "EB-1": _ep("EB-1", 7, 10)}  # 30%, 70%
    rollup = build_objectives(rows, progress, behind_threshold=0.5)
    assert "Behind" in rollup.at_risk
    assert "OnTrack" not in rollup.at_risk


def test_none_progress_objective_not_at_risk():
    rows = [("AllBad", "KR1", "EMISS-1", "")]
    rollup = build_objectives(rows, {}, behind_threshold=0.5)
    assert rollup.objectives[0].progress_pct is None
    assert rollup.at_risk == ()  # None progress is a problem, not "at risk"


def test_objective_order_preserved():
    rows = [
        ("Zeta", "KR1", "EA-1", ""),
        ("Alpha", "KR2", "EB-1", ""),
        ("Zeta", "KR3", "EC-1", ""),  # second KR of Zeta (out of contiguous order)
    ]
    progress = {k: _ep(k, 5, 10) for k in ("EA-1", "EB-1", "EC-1")}
    rollup = build_objectives(rows, progress, behind_threshold=0.0)
    names = [o.name for o in rollup.objectives]
    assert names == ["Zeta", "Alpha"]  # first-seen order; Zeta groups both KRs
    zeta = rollup.objectives[0]
    assert len(zeta.key_results) == 2
