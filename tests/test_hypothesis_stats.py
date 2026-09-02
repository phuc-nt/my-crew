"""The keep-or-kill arithmetic behind the crew shapes.

Every rule here decides whether a shape stays in the router, so each threshold is pinned
at its boundary from both sides: a verdict that quietly drifted from "≥2/3" to ">2/3"
would kill a shape on 8/12 and nobody would see it in a report full of numbers.
"""

from __future__ import annotations

import math

import pytest

from my_crew.bench import hypothesis_stats as hs

# ---- Wilson interval ---------------------------------------------------------------


def test_wilson_covers_the_point_estimate_and_stays_inside_zero_one():
    lo, hi = hs.wilson_interval(8, 12)
    assert lo < 8 / 12 < hi
    assert 0.0 <= lo and hi <= 1.0


def test_wilson_does_not_claim_certainty_on_a_perfect_dozen():
    # A normal interval on 12/12 collapses to [1, 1]; Wilson keeps daylight below 1.
    lo, hi = hs.wilson_interval(12, 12)
    assert hi == 1.0
    assert lo < 1.0
    assert lo == pytest.approx(0.757, abs=0.005)


def test_wilson_matches_the_textbook_value():
    # 0.5 at n=10, z=1.96 → [0.2366, 0.7634] to four places.
    lo, hi = hs.wilson_interval(5, 10)
    assert (round(lo, 4), round(hi, 4)) == (0.2366, 0.7634)


def test_wilson_on_an_empty_sample_is_zero_width_not_a_crash():
    assert hs.wilson_interval(0, 0) == (0.0, 0.0)


def test_wilson_rejects_more_wins_than_trials():
    with pytest.raises(ValueError):
        hs.wilson_interval(13, 12)


# ---- minimum sample ----------------------------------------------------------------


def test_minimum_sample_is_four_cases_times_three_runs():
    assert hs.MIN_PAIRS == 12
    assert hs.min_sample_met(12)
    assert not hs.min_sample_met(11)


# ---- H1: fan-out beats sprint ------------------------------------------------------


def test_h1_keeps_on_exactly_two_thirds_won_at_exactly_three_times_cost():
    v = hs.verdict("H1", wins=8, n=12, crew_cost=0.30, sprint_cost=0.10)
    assert v.keep
    assert v.reasons == ()
    assert v.metrics["win_rate"] == pytest.approx(0.667, abs=0.001)
    assert v.metrics["cost_ratio"] == 3.0


def test_h1_dies_one_win_short():
    v = hs.verdict("H1", wins=7, n=12, crew_cost=0.10, sprint_cost=0.10)
    assert not v.keep
    assert any("win rate" in r for r in v.reasons)


def test_h1_dies_when_the_crew_costs_more_than_three_times_a_sprint():
    v = hs.verdict("H1", wins=12, n=12, crew_cost=0.31, sprint_cost=0.10)
    assert not v.keep
    assert any("cost ratio" in r for r in v.reasons)


def test_h1_dies_on_a_thin_sample_even_when_every_pair_was_won():
    # 11/11 is not evidence the proposal accepts: an untested shape is not a survivor.
    v = hs.verdict("H1", wins=11, n=11, crew_cost=0.10, sprint_cost=0.10)
    assert not v.keep
    assert v.reasons == ("sample 11 < 12 pairs",)


def test_h1_reports_the_wilson_bounds_next_to_the_point_estimate():
    v = hs.verdict("H1", wins=8, n=12, crew_cost=0.1, sprint_cost=0.1)
    lo, hi = hs.wilson_interval(8, 12)
    assert (v.metrics["wilson_low"], v.metrics["wilson_high"]) == (round(lo, 3), round(hi, 3))


def test_h1_with_a_free_sprint_reports_an_infinite_ratio_as_a_kill_not_a_crash():
    v = hs.verdict("H1", wins=12, n=12, crew_cost=0.1, sprint_cost=0.0)
    assert not v.keep
    assert v.metrics["cost_ratio"] is None
    assert any("cost ratio" in r for r in v.reasons)


# ---- H2: independent review catches planted errors ---------------------------------


def test_h2_keeps_at_exactly_half_caught_and_a_quarter_disagreement():
    v = hs.verdict("H2", caught=6, seeded=12, disagreements=3, graded=12)
    assert v.keep
    assert v.metrics["catch_rate"] == 0.5
    assert v.metrics["disagreement"] == 0.25


def test_h2_dies_when_the_reviewer_misses_more_than_half():
    v = hs.verdict("H2", caught=5, seeded=12, disagreements=0, graded=12)
    assert not v.keep
    assert any("catch rate" in r for r in v.reasons)


def test_h2_dies_when_the_runs_disagree_too_often():
    # A coin-flip reviewer "catches" half; the noise bound is what separates it from a reader.
    v = hs.verdict("H2", caught=12, seeded=12, disagreements=4, graded=12)
    assert not v.keep
    assert any("disagreement" in r for r in v.reasons)


def test_h2_needs_twelve_seeded_errors():
    v = hs.verdict("H2", caught=9, seeded=9, disagreements=0, graded=9)
    assert not v.keep
    assert v.reasons == ("sample 9 < 12 seeded errors",)


# ---- H3: cheap specialists at equal quality ----------------------------------------


def test_h3_keeps_when_ties_balance_losses_and_cost_is_seventy_percent():
    v = hs.verdict("H3", wins=3, losses=3, n=12, crew_cost=0.07, sprint_cost=0.10)
    assert v.keep
    assert v.metrics["ties"] == 6
    assert v.metrics["cost_ratio"] == 0.7


def test_h3_dies_when_the_crew_loses_more_pairs_than_it_wins():
    v = hs.verdict("H3", wins=3, losses=4, n=12, crew_cost=0.01, sprint_cost=0.10)
    assert not v.keep
    assert any("lost 4 > won 3" == r for r in v.reasons)


def test_h3_dies_when_it_is_not_at_least_thirty_percent_cheaper():
    v = hs.verdict("H3", wins=6, losses=0, n=12, crew_cost=0.071, sprint_cost=0.10)
    assert not v.keep
    assert any("cost ratio" in r for r in v.reasons)


def test_h3_ties_count_toward_the_not_worse_interval():
    v = hs.verdict("H3", wins=0, losses=0, n=12, crew_cost=0.05, sprint_cost=0.10)
    assert v.keep
    assert v.metrics["wilson_low"] == round(hs.wilson_interval(12, 12)[0], 3)


# ---- dispatch ----------------------------------------------------------------------


def test_verdict_dispatches_case_insensitively_and_rejects_unknown_names():
    assert hs.verdict("h1", wins=8, n=12, crew_cost=1, sprint_cost=1).hypothesis == "H1"
    with pytest.raises(ValueError, match="H4"):
        hs.verdict("H4")


def test_every_reason_names_the_threshold_it_failed():
    v = hs.verdict("H1", wins=0, n=3, crew_cost=math.e, sprint_cost=0.1)
    assert len(v.reasons) == 3
    assert [r.split(" ")[0] for r in v.reasons] == ["sample", "win", "cost"]
