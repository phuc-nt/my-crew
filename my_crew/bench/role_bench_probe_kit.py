"""Shared shapes for the per-role probes: what a probe is, and what one run yields.

A probe is one fixed input driven through the REAL prompt builder and the REAL parser
of a model role, scored by a deterministic check. It is not a judge: nothing here asks
a second model whether the first one did well. The score is "did production code get
what it needs from this call" — a parsed verdict, a valid DAG, the right command id,
the right number in the text — because that is the only question a role scorecard
can answer without measuring the judge instead of the role.

`kind` names the failure the way production would experience it:
- `empty`      the model returned nothing (fail-open paths quietly degrade here);
- `truncated`  the completion hit the token ceiling;
- `parse`      text came back but the role's parser refused it;
- `wrong`      it parsed, and the answer is wrong for a fixed, unambiguous input;
- `error`      the call itself raised.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

FAIL_KINDS = ("empty", "truncated", "parse", "wrong", "error")


@dataclass(frozen=True)
class ProbeOutcome:
    """`tallies` are integer counters a probe wants summed across replays beyond
    ok/fail — the graders report `clean_graded`/`false_fails`/`seeded`/`caught` so the
    role scorecard can hand H4 the very numbers the calibration report uses."""

    ok: bool
    kind: str = "ok"
    detail: str = ""
    cost_usd: float | None = None
    tallies: dict[str, int] | None = None

    @staticmethod
    def passed(detail: str = "", cost: float | None = None,
               tallies: dict[str, int] | None = None) -> ProbeOutcome:
        return ProbeOutcome(True, "ok", detail, cost, tallies)

    @staticmethod
    def failed(kind: str, detail: str = "", cost: float | None = None,
               tallies: dict[str, int] | None = None) -> ProbeOutcome:
        if kind not in FAIL_KINDS:
            raise ValueError(f"unknown failure kind {kind!r}")
        return ProbeOutcome(False, kind, detail[:300], cost, tallies)


@dataclass(frozen=True)
class Probe:
    """`run(client)` performs the role's call(s) and scores them. `client` is anything
    with `.complete(messages, role=...)` — the real `LlmClient` live, a scripted fake
    in the offline tests."""

    role: str
    name: str
    run: Callable[[Any], ProbeOutcome]


def complete_text(client: Any, messages: list[dict], role: str) -> tuple[str, float | None,
                                                                      ProbeOutcome | None]:
    """One completion → (text, cost, early_failure). The early failure is set for the
    two outcomes every role shares — empty and truncated — so probes only score the
    text they actually got."""
    res = client.complete(messages, role=role)
    text = (getattr(res, "content", "") or "").strip()
    cost = getattr(res, "cost_usd", None)
    if not text:
        return "", cost, ProbeOutcome.failed("empty", cost=cost)
    if getattr(res, "truncated", False) or getattr(res, "finish_reason", "") == "length":
        return text, cost, ProbeOutcome.failed("truncated", text[-120:], cost)
    return text, cost, None


def has_english_preamble(text: str) -> bool:
    """The Telegram-truncation failure: a chain-of-thought lead-in in English before
    the Vietnamese deliverable. Only the opening is inspected — English inside a table
    or a quoted source is not a preamble."""
    head = text[:160].lower()
    return any(tok in head for tok in (" the ", "let me", "i will", "i'll", "here is",
                                       "here's", "first,", "okay,", "sure,"))
