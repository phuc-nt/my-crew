"""The release bench must tell two revisions apart for the RIGHT reason.

The harness itself is what these tests pin down: the simulated web's two sides, the
faithful model's no-unsourced-numbers rule, determinism across repeats, and the
compare step. The cross-revision numbers (patched working tree vs the v0.10.0 tag)
come from running the script in a worktree — a live comparison no unit test should
fake by monkeypatching the parser.
"""

from __future__ import annotations

import pytest

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
    assert set(report["cases"]) == {
        f"{c.name}@{effort}" for c in ALL_CASES for effort in bench.BENCHED_EFFORTS
    }


def test_every_brief_is_measured_at_both_effort_tiers():
    """What P3 claims is a SAVING, and a saving is a delta between two tiers. One tier
    alone cannot show it, so the report has to carry both for the same brief."""
    report = bench.run_suite()
    for case in ALL_CASES:
        low = report["cases"][f"{case.name}@low"]
        medium = report["cases"][f"{case.name}@medium"]
        assert low["effort"] == "low" and medium["effort"] == "medium"
        assert low["searches"] <= medium["searches"], (case.name, low, medium)
        assert low["model_role"] != medium["model_role"], (case.name, low, medium)


def test_comparing_two_reports_that_declare_different_versions_is_refused():
    """A field added between revisions reads as a behaviour change if compared blindly.
    Refusing is the only answer that cannot produce a wrong conclusion."""
    with pytest.raises(ValueError, match="format_version"):
        bench.compare_reports({"format_version": 1, "cases": {}},
                              {"format_version": 2, "cases": {}})


def test_a_baseline_from_before_the_version_field_is_still_comparable():
    """The old-tag baseline has no `format_version` at all — refusing it would block
    exactly the cross-revision comparison this mode exists for."""
    rows = bench.compare_reports({"cases": {}}, {"format_version": 2, "cases": {}})
    assert rows == []


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


def test_an_old_flat_key_baseline_is_matched_against_the_medium_tier():
    """Báo cáo từ tag cũ có khoá phẳng `case`, bản mới có `case@effort`. So thô biến
    mỗi case thành hai dòng "đổi hình dạng" và chôn mất câu đang thật sự hỏi — chi phí
    có dịch chuyển không. Các lượt chạy cũ đo đúng thứ bây giờ gọi là tier `medium`."""
    base = {"cases": {"c3_prose": {"searches": 5}}}  # không khai format_version
    cand = {"format_version": bench.FORMAT_VERSION,
            "cases": {"c3_prose@medium": {"searches": 3},
                      "c3_prose@low": {"searches": 2}}}

    rows = bench.compare_reports(base, cand)
    by_case = {(r["case"], r["field"]): r for r in rows}

    # Tier medium so được theo trục thật, không phải theo sự hiện diện.
    moved = by_case[("c3_prose@medium", "searches")]
    assert (moved["baseline"], moved["candidate"]) == (5, 3)
    # Tier low chỉ bên mới có — đúng sự thật (tier đó chưa tồn tại), một dòng chứ ba.
    assert by_case[("c3_prose@low", "presence")]["baseline"] is False


def test_two_unversioned_reports_are_compared_as_peers():
    """Cùng không khai phiên bản nghĩa là hai báo cáo cùng thời. Đổi tên khoá một bên
    khi đó là TỰ TẠO ra lệch khoá chứ không phải xoá lệch khoá."""
    base = {"cases": {"c3_prose": {"searches": 5}}}
    cand = {"cases": {"c3_prose": {"searches": 3}}}
    rows = bench.compare_reports(base, cand)
    assert [r["field"] for r in rows] == ["searches"]
