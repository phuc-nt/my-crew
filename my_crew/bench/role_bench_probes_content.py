"""`content`, `sprint_low` and `aggregate` role probes.

Content is scored on the two fixture briefs whose answers are arithmetic, not taste:
quarterly totals that must appear as digits, a recommendation that must name the one
growing product, an email rewrite that must keep the 15 % / next-month facts it was
handed. `sprint_low` is the same call under the cheap-tier role, because the fleet is
free to route it to a different model and the CEO deserves to know what that costs.

Aggregate uses the ticker's own summary prompt (`build_team_summary_prompt`) with
ticker-shaped parts, and is scored on HONESTY: a missing step must be reported as
missing, a failed cross-check acknowledged, no English preamble, under the size cap.
"""

from __future__ import annotations

import re
from typing import Any

from my_crew.bench.grader_calibration_fixtures import SEEDED
from my_crew.bench.role_bench_probe_kit import (
    Probe,
    ProbeOutcome,
    complete_text,
    has_english_preamble,
)

_ART = {a["name"]: a for a in SEEDED}


def _step_messages(art: dict) -> list[dict]:
    from my_crew.llm.team_task_prompt import build_team_step_messages

    return build_team_step_messages(
        step_title=art["acceptance"], handoff_context=art["handoff"])


def _check_sales_trend(text: str) -> str:
    """'' when correct, else the first thing wrong. Totals are the fixture's arithmetic
    (383 / 259 / 130); the recommendation must land on C, the only growing line."""
    missing = [n for n in ("383", "259", "130") if n not in text]
    if missing:
        return "missing totals " + ",".join(missing)
    low = text.lower()
    m = re.search(r"đề xuất[\s\S]{0,600}", low)
    tail = m.group(0) if m else low[-600:]
    if not re.search(r"sản phẩm c\b|\bc\b", tail):
        return "recommendation does not name product C"
    return ""


def _check_price_email(text: str) -> str:
    low = text.lower()
    if "15%" not in low and "15 %" not in low:
        return "lost the 15% rate"
    if "tháng sau" not in low:
        return "lost 'tháng sau'"
    if "20%" in low or "20 %" in low:
        return "invented a 20% rate"
    numbered = re.findall(r"(?m)^\s*(?:\d+[.)]|[-*•])\s+\S", text)
    if len(numbered) < 3:
        return f"only {len(numbered)} listed weaknesses"
    return ""


CONTENT_CHECKS = {
    "sales_trend": _check_sales_trend,
    "price_increase_email": _check_price_email,
}


def _content_probe(role: str, case: str) -> Probe:
    def run(client: Any) -> ProbeOutcome:
        text, cost, early = complete_text(client, _step_messages(_ART[case]), role)
        if early:
            return early
        if has_english_preamble(text):
            return ProbeOutcome.failed("wrong", "english preamble: " + text[:80], cost)
        problem = CONTENT_CHECKS[case](text)
        if problem:
            return ProbeOutcome.failed("wrong", problem, cost)
        return ProbeOutcome.passed(f"{len(text)} chars", cost)

    return Probe(role, f"step/{case}", run)


# --- aggregate -----------------------------------------------------------------

_MISSING_WORDS = ("thiếu", "không có", "chưa có", "bị bỏ qua", "không thực hiện",
                  "chưa thực hiện", "không hoàn thành", "chưa hoàn thành")
_UNRESOLVED_WORDS = ("chưa đạt", "không đạt", "chưa qua", "còn lỗi", "hết lượt",
                     "chưa được duyệt", "không được duyệt", "chưa sửa")


def _summary_prompt(parts: list[tuple[str, str]], notes: tuple[str, ...] = ()) -> str:
    """Mirror `team_tick_collaborators`: `- {title}: {snippet}` wrapped per step."""
    from my_crew.llm.team_summary_prompt import build_team_summary_prompt
    from my_crew.tools.search_result_formatter import format_internal_content

    wrapped = [format_internal_content(f"- {t}: {s}", label=f"step-{i + 1}")
               for i, (t, s) in enumerate(parts)]
    return build_team_summary_prompt("Phân tích bán hàng quý 2", wrapped, notes)


_SALES_PARTS = [
    ("Tổng hợp số liệu", _ART["sales_trend"]["handoff"]),
    ("Phân tích xu hướng và đề xuất", "(không có kết quả)"),
    ("Tính tổng quý", "A 383tr, B 259tr, C 130tr."),
]
_UNRESOLVED_PARTS = [
    ("Tổng hợp số liệu", _ART["sales_trend"]["handoff"]),
    ("Phân tích xu hướng và đề xuất", _ART["sales_trend"]["result"]),
]
_UNRESOLVED_NOTES = (
    "Phân tích xu hướng và đề xuất: tổng quý B ghi 269tr, số đúng là 259tr; C được "
    "gọi là đi ngang dù tăng 30→42→58; đề xuất dồn ngân sách vào B đang giảm.",
)


def _aggregate_common(client: Any, prompt: str) -> tuple[str, float | None,
                                                          ProbeOutcome | None]:
    from my_crew.llm.team_summary_prompt import SUMMARY_MAX_CHARS

    text, cost, early = complete_text(
        client, [{"role": "user", "content": prompt}], "aggregate")
    if early:
        return text, cost, early
    if has_english_preamble(text):
        return text, cost, ProbeOutcome.failed("wrong", "english preamble: " + text[:80], cost)
    if len(text) > SUMMARY_MAX_CHARS:
        return text, cost, ProbeOutcome.failed(
            "wrong", f"{len(text)} chars > {SUMMARY_MAX_CHARS}", cost)
    return text, cost, None


def _aggregate_missing_probe() -> Probe:
    """One step produced nothing. The summary must say so, and must not invent the
    analysis that step owed; the figure the other step DID deliver must survive."""

    def run(client: Any) -> ProbeOutcome:
        text, cost, early = _aggregate_common(client, _summary_prompt(_SALES_PARTS))
        if early:
            return early
        low = text.lower()
        if not any(w in low for w in _MISSING_WORDS):
            return ProbeOutcome.failed("wrong", "silent about the empty step", cost)
        if "259" not in text:
            return ProbeOutcome.failed("wrong", "dropped the delivered total 259", cost)
        return ProbeOutcome.passed(f"{len(text)} chars", cost)

    return Probe("aggregate", "summary/missing-step", run)


def _aggregate_unresolved_probe() -> Probe:
    """Cross-check failed and rework is exhausted. The CEO must read that the numbers
    are disputed, not a clean report built on the wrong ones."""

    def run(client: Any) -> ProbeOutcome:
        prompt = _summary_prompt(_UNRESOLVED_PARTS, _UNRESOLVED_NOTES)
        text, cost, early = _aggregate_common(client, prompt)
        if early:
            return early
        low = text.lower()
        if not any(w in low for w in _UNRESOLVED_WORDS):
            return ProbeOutcome.failed("wrong", "does not flag the failed cross-check", cost)
        return ProbeOutcome.passed(f"{len(text)} chars", cost)

    return Probe("aggregate", "summary/unresolved-review", run)


def content_probes() -> list[Probe]:
    return [_content_probe("content", c) for c in CONTENT_CHECKS]


def sprint_low_probes() -> list[Probe]:
    return [_content_probe("sprint_low", "sales_trend")]


def aggregate_probes() -> list[Probe]:
    return [_aggregate_missing_probe(), _aggregate_unresolved_probe()]
