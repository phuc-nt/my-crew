"""`roles` bench: đo vai nào đang tốt trên model của fleet, và chứng minh nó ĐO ĐƯỢC.

Toàn bộ chạy offline bằng client giả có kịch bản: mỗi bài cắm một hành vi model cụ thể
(trả rỗng, trả JSON hỏng, trả đúng hình nhưng sai, cắt cụt) rồi khẳng định scorecard
gọi tên đúng loại lỗi. Con số tuyệt đối không quan trọng; thứ cần chứng minh là mỗi
loại hỏng của model hiện ra như một `kind` riêng, và bảng so sánh ĐỔI khi hành vi đổi.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from my_crew.bench import role_bench
from my_crew.bench.role_bench_probe_kit import Probe, ProbeOutcome
from my_crew.bench.role_bench_probes_content import CONTENT_CHECKS
from my_crew.bench.role_bench_probes_review import caught_errors, review_probes


@dataclass
class _Result:
    content: str
    cost_usd: float | None = 0.001
    truncated: bool = False
    finish_reason: str = "stop"
    model: str = "fake"
    prompt_tokens: int = 1
    completion_tokens: int = 1
    fallback_from: str | None = None


class _Scripted:
    """Trả lời theo vai: `script[role]` là một chuỗi, một `_Result`, hoặc một hàm nhận
    messages. Ghi lại từng lời gọi để bài test soi được prompt thật đã đi qua."""

    def __init__(self, script: dict) -> None:
        self.script = script
        self.calls: list[tuple[str, list[dict]]] = []

    def complete(self, messages, role="content", **_):
        self.calls.append((role, messages))
        answer = self.script[role]
        if callable(answer):
            answer = answer(messages)
        if isinstance(answer, _Result):
            return answer
        return _Result(answer)


def _probe(role: str, name: str, outcome: ProbeOutcome) -> Probe:
    return Probe(role, name, lambda client: outcome)


# --- phân loại kết quả ----------------------------------------------------------------


def test_every_fleet_role_has_at_least_one_probe():
    # Vai thêm vào `MODEL_ROLES` mà không có probe sẽ mãi đọc là `unmeasured`.
    assert role_bench.uncovered_roles(role_bench.all_probes(intake=lambda *a, **k: None)) == []


def test_intake_probe_uses_the_injected_seam_not_the_environment():
    from my_crew.bench.role_bench_probes_plan import plan_probes

    class _Plan:
        goal = "Rút gọn"
        acceptance = "Có đủ mục"
        assigned_to = "writer"
        needs_web = True

    seen = []

    def _intake(brief, staff, pic_requested=""):
        seen.append(brief)
        return _Plan(), 0.0

    probes = [p for p in plan_probes(intake=_intake) if p.name.startswith("intake/")]
    assert probes, "no intake probe registered"
    outcome = probes[0].run(client=None)
    assert outcome.ok, outcome
    assert seen, "the injected intake was never called"


def test_empty_completion_is_the_empty_kind():
    client = _Scripted({"review": ""})
    probe = next(p for p in review_probes() if p.name.startswith("self_check/clean/"))
    outcome = probe.run(client)
    assert (outcome.ok, outcome.kind) == (False, "empty")


def test_truncated_completion_is_the_truncated_kind():
    client = _Scripted({"review": _Result('{"passed": tr', finish_reason="length")})
    probe = next(p for p in review_probes() if p.name.startswith("review/clean/"))
    outcome = probe.run(client)
    assert (outcome.ok, outcome.kind) == (False, "truncated")


def test_unparseable_verdict_is_the_parse_kind():
    client = _Scripted({"review": "Đạt rồi, không có lỗi gì đâu."})
    probe = next(p for p in review_probes() if p.name.startswith("self_check/clean/"))
    outcome = probe.run(client)
    assert (outcome.ok, outcome.kind) == (False, "parse")


def test_a_grader_that_fails_clean_work_is_a_false_fail_with_h4_tallies():
    client = _Scripted({"review": json.dumps(
        {"passed": False, "failures": ["thiếu nguồn"], "confidence": 0.9})})
    probe = next(p for p in review_probes() if p.name.startswith("self_check/clean/"))
    outcome = probe.run(client)
    assert (outcome.ok, outcome.kind) == (False, "wrong")
    assert outcome.tallies == {"clean_graded": 1, "false_fails": 1}


def test_a_grader_that_passes_seeded_work_is_wrong_and_caught_nothing():
    client = _Scripted({"review": json.dumps({"passed": True, "failures": []})})
    probe = next(p for p in review_probes() if p.name == "review/seeded/sales_trend")
    outcome = probe.run(client)
    assert (outcome.ok, outcome.kind) == (False, "wrong")
    assert outcome.tallies["caught"] == 0
    assert outcome.tallies["seeded"] == 3


def test_a_grader_that_names_a_planted_defect_passes_the_seeded_probe():
    client = _Scripted({"review": json.dumps(
        {"passed": False, "failures": ["Tổng quý B ghi 269tr, tính lại là 259tr"]})})
    probe = next(p for p in review_probes() if p.name == "review/seeded/sales_trend")
    outcome = probe.run(client)
    assert outcome.ok, outcome
    assert outcome.tallies == {"seeded": 3, "caught": 1}


def test_caught_errors_matches_markers_case_insensitively():
    art = {"errors": [{"id": "x", "markers": ["Quý Sau"]}, {"id": "y", "markers": ["zzz"]}]}
    assert caught_errors(art, ["đổi thành quý sau"]) == ["x"]


def test_a_raising_probe_is_the_error_kind_and_does_not_abort_the_suite():
    def boom(_client):
        raise RuntimeError("socket closed")

    probes = [Probe("util", "boom", boom),
              _probe("util", "fine", ProbeOutcome.passed())]
    report = role_bench.run_suite(None, k=2, probes=probes)
    util = report["roles"]["util"]
    assert util["fails"] == {"error": 2}
    assert (util["ok"], util["n"]) == (2, 4)
    assert "RuntimeError: socket closed" in util["probes"][0]["details"][0]


# --- kiểm tra nội dung ----------------------------------------------------------------


def test_sales_trend_check_demands_the_totals_and_the_growing_product():
    check = CONTENT_CHECKS["sales_trend"]
    assert "missing totals" in check("A tăng, B giảm, C tăng. Đề xuất: sản phẩm C.")
    assert "product C" in check("A 383tr, B 259tr, C 130tr. Đề xuất: dồn vào sản phẩm B.")
    assert check("A 383tr, B 259tr, C 130tr.\n## Đề xuất\nDồn ngân sách vào sản phẩm C.") == ""


def test_price_email_check_keeps_the_facts_and_counts_weaknesses():
    check = CONTENT_CHECKS["price_increase_email"]
    good = ("1. Không nêu giá trị\n2. Đẩy khách đi\n3. Không có kênh liên hệ\n\n"
            "Kính gửi Quý khách, giá tăng 15% từ tháng sau.")
    assert check(good) == ""
    assert "20%" in check(good.replace("giá tăng 15%", "giá cũ tăng 15%, nay tăng 20%"))
    assert "tháng sau" in check(good.replace("tháng sau", "quý sau"))
    assert "listed weaknesses" in check(good.replace("3. Không có kênh liên hệ\n", ""))


# --- gộp theo vai và bảng so sánh ---------------------------------------------------


def test_role_rate_pools_over_probes_and_replays_with_a_wilson_interval():
    probes = [_probe("content", "a", ProbeOutcome.passed()),
              _probe("content", "b", ProbeOutcome.failed("wrong", "off"))]
    report = role_bench.run_suite(None, k=3, probes=probes, model="fake")
    content = report["roles"]["content"]
    assert (content["ok"], content["n"], content["rate"]) == (3, 6, 0.5)
    assert content["wilson_low"] < 0.5 < content["wilson_high"]
    assert content["verdict"] == "weak"
    assert content["fails"] == {"wrong": 3}
    assert report["roles"]["advisor"]["verdict"] == "unmeasured"
    assert report["model"] == "fake"


@pytest.mark.parametrize("ok, n, verdict", [
    (0, 0, "unmeasured"), (9, 10, "good"), (8, 10, "watch"), (7, 10, "weak"), (3, 3, "good"),
])
def test_role_verdict_thresholds(ok, n, verdict):
    assert role_bench.role_verdict(ok, n) == verdict


def test_review_role_carries_the_h4_calibration_from_probe_tallies():
    probes = [
        _probe("review", "clean", ProbeOutcome.passed(tallies={"clean_graded": 1,
                                                                "false_fails": 0})),
        _probe("review", "seeded", ProbeOutcome.passed(tallies={"seeded": 3, "caught": 2})),
    ]
    report = role_bench.run_suite(None, k=4, probes=probes)
    h4 = report["roles"]["review"]["h4"]
    assert (h4["clean_graded"], h4["false_fails"], h4["seeded"], h4["caught"]) == (4, 0, 12, 8)
    assert h4["keep"] is False  # 4 clean gradings is under MIN_PAIRS: honest, not green
    assert any("clean gradings" in r for r in h4["reasons"])


def test_unknown_role_filter_raises_instead_of_printing_a_clean_report():
    with pytest.raises(ValueError, match="unknown roles"):
        role_bench.run_suite(None, k=1, roles=["reviewer"], probes=[])


def test_role_filter_narrows_the_report_to_the_requested_roles():
    probes = [_probe("util", "u", ProbeOutcome.passed()),
              _probe("plan", "p", ProbeOutcome.passed())]
    report = role_bench.run_suite(None, k=1, roles=["util"], probes=probes)
    assert list(report["roles"]) == ["util"]


def test_compare_sees_a_role_that_dropped_and_names_the_probe():
    probes_ok = [_probe("util", "memory", ProbeOutcome.passed())]
    probes_bad = [_probe("util", "memory", ProbeOutcome.failed("parse", "no json"))]
    base = role_bench.run_suite(None, k=2, probes=probes_ok)
    cand = role_bench.run_suite(None, k=2, probes=probes_bad)
    rows = role_bench.compare_roles(base, cand)
    assert {(r["case"], r["field"]) for r in rows} == {
        ("util", "rate"), ("util", "verdict"), ("util/memory", "ok")}
    assert role_bench.compare_roles(base, base) == []


def test_compare_refuses_a_k_or_format_mismatch():
    a = role_bench.run_suite(None, k=1, probes=[])
    b = role_bench.run_suite(None, k=2, probes=[])
    with pytest.raises(ValueError, match="khác k"):
        role_bench.compare_roles(a, b)
    with pytest.raises(ValueError, match="format_version"):
        role_bench.compare_roles(a, {**a, "format_version": 99})


# --- CLI ---------------------------------------------------------------------------


def test_cli_roles_default_k_matches_the_module_default():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "run_sprint_benchmark", Path("scripts/run-sprint-benchmark.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import argparse

    captured = {}
    real = argparse.ArgumentParser.parse_args

    def fake_parse(self, *a, **kw):
        ns = real(self, ["roles"])
        captured.update(vars(ns))
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = fake_parse
    try:
        with pytest.raises(SystemExit):
            mod.main()
    finally:
        argparse.ArgumentParser.parse_args = real
    assert captured["k"] == role_bench.DEFAULT_K
    assert captured["role"] is None


def test_decompose_probe_scores_the_plan_the_product_would_accept():
    """The assign path hands the lone terminal step back to the PIC before validating;
    a plan that names one PIC and gives the summary to another agent is therefore a
    pass, not a "parse" failure — the bench must measure the same path."""
    from my_crew.bench.role_bench_probes_plan import plan_probes

    plan = json.dumps({"title": "T", "pic_id": "analyst", "steps": [
        {"step_id": "research", "title": "r", "assigned_to": "researcher", "deps": []},
        {"step_id": "analysis", "title": "a", "assigned_to": "analyst",
         "deps": ["research"]},
        {"step_id": "summary", "title": "s", "assigned_to": "writer",
         "deps": ["research", "analysis"]},
    ]})
    probe = next(p for p in plan_probes() if p.name.startswith("decompose/"))
    outcome = probe.run(_Scripted({"plan": plan}))
    assert outcome.ok, outcome


# --- ai phục vụ lời gọi ----------------------------------------------------------------


def test_each_replay_names_the_upstream_that_served_it():
    # OpenRouter xoay một alias qua nhiều upstream; một lượt hỏng phải quy được cho
    # upstream nào, không đổ oan cho model.
    served = iter(["DeepSeek", "OpenInference", "DeepSeek"])

    def _probe_fn(client):
        res = client.complete([{"role": "user", "content": "x"}], role="content")
        return ProbeOutcome.passed() if res.content == "good" else ProbeOutcome.failed(
            "wrong", res.content)

    class _Routed:
        def complete(self, messages, role="content", **_):
            provider = next(served)
            r = _Result("good" if provider == "DeepSeek" else "ư ư ư")
            r.provider = provider
            return r

    report = role_bench.run_suite(_Routed(), k=3, probes=[Probe("content", "p", _probe_fn)],
                                  model="fake")
    content = report["roles"]["content"]
    assert content["providers"] == {"DeepSeek": 2, "OpenInference": 1}
    assert content["fails_by_provider"] == {"OpenInference": 1}
    details = content["probes"][0]["details"]
    assert details[0].endswith("@DeepSeek")
    assert details[1].startswith("wrong: ư ư ư") and details[1].endswith("@OpenInference")


def test_a_client_without_a_provider_field_is_counted_as_unknown():
    def _probe_fn(client):
        client.complete([{"role": "user", "content": "x"}], role="content")
        return ProbeOutcome.passed()

    report = role_bench.run_suite(_Scripted({"content": "ok"}), k=1,
                                  probes=[Probe("content", "p", _probe_fn)], model="fake")
    content = report["roles"]["content"]
    assert content["providers"] == {"?": 1}
    assert content["probes"][0]["details"] == ["ok @?"]


def test_a_probe_that_never_calls_the_model_has_no_provider_suffix():
    report = role_bench.run_suite(None, k=1, probes=[_probe("content", "a", ProbeOutcome.passed())],
                                  model="fake")
    content = report["roles"]["content"]
    assert content["providers"] == {}
    assert content["probes"][0]["details"] == ["ok"]


# --- vai advisor: im lặng thật khác với note bị cách ly ---------------------------------


def _advisor_403_probe():
    from my_crew.bench.role_bench_probes_util_advisor import advisor_probes

    return next(p for p in advisor_probes() if p.name == "sweep/repeated-403")


def test_a_note_quarantined_for_language_drift_does_not_score_against_the_advisor():
    """Model trôi khỏi tiếng Việt giữa câu: rào chắn nuốt note là đúng việc của nó.

    Advisor ĐÃ nhìn ra vòng lặp 403; chấm nó là `wrong` sẽ đọc lỗi ngôn ngữ của model
    thành lỗi của vai advisor, và khiến điểm vai tụt vì một thứ nó làm đúng.
    """
    drifted = ('{"severity": "concern", "note": "URL đã 403 lặp 9 lần și de fiecare dată '
               'aceeași eroare — schimbă sursa."}')
    outcome = _advisor_403_probe().run(_Scripted({"advisor": drifted}))
    assert outcome.ok and "quarantined" in outcome.detail


def test_an_overlong_note_is_also_read_as_a_quarantine_not_a_miss():
    from my_crew.runtime.advisor_sweep import MAX_NOTE_CHARS

    runaway = json.dumps({"severity": "concern", "note": "lặ" * (MAX_NOTE_CHARS + 1)},
                         ensure_ascii=False)
    outcome = _advisor_403_probe().run(_Scripted({"advisor": runaway}))
    assert outcome.ok and "quarantined" in outcome.detail


def test_a_genuinely_silent_advisor_still_fails_the_403_probe():
    # Rào chắn không được trở thành chỗ trốn: không nêu mối lo nào thì vẫn là trượt.
    for reply in ('{"severity": "silent", "note": ""}', "không phải JSON", ""):
        outcome = _advisor_403_probe().run(_Scripted({"advisor": reply}))
        assert not outcome.ok and outcome.kind == "wrong", reply
