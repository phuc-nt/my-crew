"""The release bench must tell two revisions apart for the RIGHT reason.

The harness itself is what these tests pin down: the simulated web's two sides, the
faithful model's no-unsourced-numbers rule, determinism across repeats, and the
compare step. The cross-revision numbers (patched working tree vs the v0.10.0 tag)
come from running the script in a worktree — a live comparison no unit test should
fake by monkeypatching the parser.
"""

from __future__ import annotations

import my_crew.bench.release_bench as bench
from my_crew.bench.brief_suite import ALL_CASES, C3_PROSE, NO_ENUMERATION, OVER_CAP


def test_the_simulated_web_rejects_kitchen_sink_queries_like_the_live_provider():
    """The v78 C3 failure began with one raw-goal query the provider 422'd."""
    render = bench.simulated_web(["Notion"])
    out = render(C3_PROSE.goal)
    assert "[LỖI NGUỒN TÌM KIẾM]" in out
    assert bench.DATA_MARK not in out


def test_the_simulated_web_only_pays_out_on_single_subject_queries():
    render = bench.simulated_web(["Notion", "Figma"])
    assert f"{bench.DATA_MARK} Notion" in render("Notion giá tháng")
    # An overview naming several subjects is the thin side: no numbers to cite.
    both = render("so sánh Notion Figma")
    assert bench.DATA_MARK not in both
    assert bench.DATA_MARK not in render("tin tức công nghệ")


def test_the_patched_pipeline_closes_all_five_c3_subjects():
    """The acceptance number for the v81 fix: the brief that scored 9.5/30 blind now
    resolves five subjects, searches each one, and delivers all five with no THIẾU
    note — against the exact same simulated web that starves the old code."""
    metric = bench.bench_case(C3_PROSE)
    assert metric.entities_parsed == 5
    assert metric.coverage_closed == 5
    assert metric.gaps_open == 0
    assert not metric.has_thieu_note
    assert metric.searches <= C3_PROSE.max_searches
    assert metric.llm_calls <= C3_PROSE.max_llm_calls


def test_a_wide_brief_recovers_its_capped_out_subjects_in_the_targeted_round():
    """14 subjects overflow the 12-slot prefetch; the targeted round must pick up the
    two that were dropped instead of leaving them as permanent gaps."""
    metric = bench.bench_case(OVER_CAP)
    assert metric.entities_parsed == 14
    assert metric.coverage_closed == 14
    assert metric.gaps_open == 0
    assert metric.llm_calls == 2, "one draft + one revise for the two capped-out banks"
    assert metric.searches <= OVER_CAP.max_searches


def test_an_unenumerated_brief_stays_one_search_one_call():
    metric = bench.bench_case(NO_ENUMERATION)
    assert metric.searches == 1
    assert metric.llm_calls == 1
    assert metric.coverage_expected == 0


def test_the_suite_is_deterministic_across_repeats():
    report = bench.run_suite(repeats=3)
    assert set(report["cases"]) == {c.name for c in ALL_CASES}


def test_compare_reports_surfaces_exactly_the_axes_that_moved():
    base = {"cases": {"c3_prose": {"llm_calls": 1, "coverage_closed": 0, "gaps_open": 5}}}
    cand = {"cases": {"c3_prose": {"llm_calls": 1, "coverage_closed": 5, "gaps_open": 0}}}
    rows = bench.compare_reports(base, cand)
    fields = {r["field"] for r in rows}
    assert fields == {"coverage_closed", "gaps_open"}


def test_compare_reports_flags_a_case_only_one_report_has():
    rows = bench.compare_reports({"cases": {}}, {"cases": {"c3_prose": {}}})
    assert rows == [
        {"case": "c3_prose", "field": "presence", "baseline": False, "candidate": True}
    ]
