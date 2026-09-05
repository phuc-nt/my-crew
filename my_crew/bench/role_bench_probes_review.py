"""`review` role probes: the graders, measured two-sided.

Self-check and peer review are the same instrument seen from two prompts; each is
scored on CLEAN artifacts (must pass — a false fail is a rework round the CEO pays for)
and on SEEDED ones (must fail AND name at least one planted defect — a grader that
fails everything is not catching anything). The stuck judge rounds out the role: its
ruling must parse and obey the roster, since code re-gates nothing it cannot read.

The tallies feed `hypothesis_stats.verdict_calibration` (H4) unchanged, so the role
scorecard and the calibration report cannot drift apart.
"""

from __future__ import annotations

from typing import Any

from my_crew.bench.grader_calibration_fixtures import CLEAN, SEEDED
from my_crew.bench.role_bench_probe_kit import Probe, ProbeOutcome, complete_text

GRADERS = ("self_check", "review")


def _grade(grader: str, client: Any, art: dict, result_text: str):
    """One grading call through the real builder + parser → ((verdict, cost), None) or
    (None, early ProbeOutcome failure)."""
    from my_crew.agent.review_graph import ReviewVerdictError, parse_review_verdict
    from my_crew.llm.team_task_check_prompt import (
        CheckVerdictError,
        build_self_check_messages,
        parse_check_verdict,
    )
    from my_crew.llm.team_task_prompt import build_review_messages

    if grader == "self_check":
        messages = build_self_check_messages(
            result_text=result_text, acceptance=art["acceptance"], handoff=art["handoff"])
        parse = parse_check_verdict
    else:
        messages = build_review_messages(
            result_text=result_text, acceptance=art["acceptance"], handoff=art["handoff"])
        parse = parse_review_verdict
    text, cost, early = complete_text(client, messages, "review")
    if early:
        return None, early
    try:
        return (parse(text), cost), None
    except (CheckVerdictError, ReviewVerdictError) as exc:
        return None, ProbeOutcome.failed("parse", str(exc), cost)


def caught_errors(art: dict, failures: list[str]) -> list[str]:
    """Ids of the planted defects whose markers appear in the grader's failure list."""
    blob = " ".join(failures).lower()
    return [e["id"] for e in art["errors"] if any(m.lower() in blob for m in e["markers"])]


def _clean_probe(grader: str, art: dict) -> Probe:
    def run(client: Any) -> ProbeOutcome:
        graded, early = _grade(grader, client, art, CLEAN[art["name"]])
        if early:
            return early
        verdict, cost = graded
        if verdict.passed:
            return ProbeOutcome.passed("passed clean", cost,
                                       {"clean_graded": 1, "false_fails": 0})
        return ProbeOutcome.failed("wrong", "false fail: " + "; ".join(verdict.failures), cost,
                                   {"clean_graded": 1, "false_fails": 1})

    return Probe("review", f"{grader}/clean/{art['name']}", run)


def _seeded_probe(grader: str, art: dict) -> Probe:
    def run(client: Any) -> ProbeOutcome:
        graded, early = _grade(grader, client, art, art["result"])
        if early:
            return early
        verdict, cost = graded
        caught = [] if verdict.passed else caught_errors(art, list(verdict.failures))
        tallies = {"seeded": len(art["errors"]), "caught": len(caught)}
        detail = f"caught={len(caught)}/{len(art['errors'])} {','.join(caught)}"
        if verdict.passed:
            return ProbeOutcome.failed("wrong", "passed seeded artifact", cost, tallies)
        if not caught:
            return ProbeOutcome.failed(
                "wrong", "failed but named no planted defect: " + "; ".join(verdict.failures),
                cost, tallies)
        return ProbeOutcome.passed(detail, cost, tallies)

    return Probe("review", f"{grader}/seeded/{art['name']}", run)


STUCK_ROSTER = ["researcher (Tra cứu thị trường)", "writer (Viết báo cáo)"]
STUCK_BRIEF = (
    "Việc: Bảng giá xe máy điện 2026\n"
    "Bước: Tra giá bán lẻ 3 dòng xe chủ lực của VinFast, Yadea, Dat Bike (analyst)\n"
    "Tiêu chí đạt: bảng 3 dòng × giá niêm yết, mỗi dòng ghi nguồn và ngày truy cập.\n\n"
    "Kết quả bước nộp:\n"
    "Tôi không có công cụ tra cứu web nên không lấy được giá niêm yết hiện tại. "
    "Theo trí nhớ: VinFast Evo200 khoảng 22tr, Yadea ~18tr, Dat Bike ~40tr. "
    "Không có nguồn.\n\n"
    "Bước tự chấm trượt ở những điểm sau:\n"
    "- Không có nguồn và ngày truy cập cho bất kỳ dòng nào\n"
    "- Giá là ước đoán, không phải giá niêm yết"
)


def _stuck_probe() -> Probe:
    """The worker said it has no web tool; the roster offers a researcher. The ruling
    must parse; `reassign` must name a roster id; `retry_with_guidance` must carry
    guidance — the two per-decision requirements code refuses otherwise. `accept` of
    sourceless guesses is the wrong ruling regardless of form."""

    def run(client: Any) -> ProbeOutcome:
        from my_crew.llm.stuck_judgement_prompt import (
            StuckVerdictError,
            build_stuck_judge_messages,
            parse_stuck_verdict,
        )

        text, cost, early = complete_text(
            client, build_stuck_judge_messages(STUCK_BRIEF, STUCK_ROSTER), "review")
        if early:
            return early
        try:
            v = parse_stuck_verdict(text)
        except StuckVerdictError as exc:
            return ProbeOutcome.failed("parse", str(exc), cost)
        roster_ids = [r.split(" ", 1)[0] for r in STUCK_ROSTER]
        detail = f"{v.decision} to={v.assign_to or '-'}"
        if v.decision == "reassign" and v.assign_to not in roster_ids:
            return ProbeOutcome.failed("wrong", f"{detail} off roster", cost)
        if v.decision == "retry_with_guidance" and not v.guidance:
            return ProbeOutcome.failed("wrong", f"{detail} blank guidance", cost)
        if v.decision == "accept":
            return ProbeOutcome.failed("wrong", f"{detail}: accepted sourceless guesses", cost)
        return ProbeOutcome.passed(detail, cost)

    return Probe("review", "stuck_judge/no-web-tool", run)


def review_probes() -> list[Probe]:
    probes: list[Probe] = []
    for grader in GRADERS:
        probes += [_clean_probe(grader, a) for a in SEEDED]
        probes += [_seeded_probe(grader, a) for a in SEEDED]
    probes.append(_stuck_probe())
    return probes
