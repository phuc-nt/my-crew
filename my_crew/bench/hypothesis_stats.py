"""Keep-or-kill arithmetic for the crew-shape hypotheses.

Each crew shape the router may pick exists on a hypothesis: fan-out beats a sprint on
breadth (H1), an independent reviewer catches planted errors (H2), cheap specialists under
a strong coordinator cost less at equal judged quality (H3). A shape whose hypothesis
dies is removed from the router — so the arithmetic that decides "dies" must be fixed
BEFORE the numbers arrive, and must be dumb enough to audit by hand.

Thresholds are borrowed from dandori's routing bench: at least 4 cases × 3 runs before
any verdict counts, and a Wilson interval on every proportion so a 3/4 that could be
2/4 is reported as such. The keep rule itself uses the point estimate; the lower bound
is reported next to it so a reader can see how thin the evidence is. Nothing in here
calls a model or reads a store: it turns tallies into a verdict, and that is all.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: Minimum paired observations before a verdict is more than an anecdote: 4 cases × 3 runs.
MIN_CASES = 4
MIN_RUNS = 3
MIN_PAIRS = MIN_CASES * MIN_RUNS

#: The kill lines, one per hypothesis, exactly as the proposal stated them.
H1_MIN_WIN_RATE = 2 / 3
H1_MAX_COST_RATIO = 3.0
H2_MIN_CATCH_RATE = 0.5
H2_MAX_DISAGREEMENT = 0.25
H3_MAX_COST_RATIO = 0.7


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for `wins` successes in `n` trials.

    Chosen over the normal approximation because the bench sits at n = 12: a 12/12
    normal interval collapses to [1, 1], which reads as certainty the sample cannot
    carry. Returns (0.0, 0.0) for an empty sample rather than dividing by zero.
    """
    if n <= 0:
        return 0.0, 0.0
    if wins < 0 or wins > n:
        raise ValueError(f"wins={wins} outside 0..{n}")
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def min_sample_met(n: int, k: int = MIN_PAIRS) -> bool:
    """True when `n` observations reach the minimum sample `k`."""
    return n >= k


@dataclass(frozen=True)
class HypothesisVerdict:
    """What the bench concluded about one hypothesis, with the numbers it used.

    `keep` is False whenever the sample is too small — an untested shape is not a
    surviving shape. `reasons` names every failed condition so the report can quote
    the exact line that killed it.
    """

    hypothesis: str
    keep: bool
    reasons: tuple[str, ...]
    metrics: dict = field(default_factory=dict)


def _ratio(numerator: float, denominator: float) -> float:
    """Cost ratio rounded to six places so 0.07/0.10 sits ON the 0.70 line, not a float
    hair above it; an unpriced baseline is an infinite ratio, never a division error."""
    return math.inf if denominator <= 0 else round(numerator / denominator, 6)


def verdict_h1(*, wins: int, n: int, crew_cost: float, sprint_cost: float) -> HypothesisVerdict:
    """H1: fan-out beats sprint on judged quality at ≤3× cost.

    `wins` = judged pairs the crew won outright (a tie is not a win: the hypothesis
    claims the crew is BETTER, and a tie at triple the price is a loss for the CEO).
    """
    reasons: list[str] = []
    win_rate = wins / n if n else 0.0
    lo, hi = wilson_interval(wins, n)
    cost_ratio = _ratio(crew_cost, sprint_cost)
    if not min_sample_met(n):
        reasons.append(f"sample {n} < {MIN_PAIRS} pairs")
    if win_rate < H1_MIN_WIN_RATE:
        reasons.append(f"win rate {win_rate:.2f} < {H1_MIN_WIN_RATE:.2f}")
    if cost_ratio > H1_MAX_COST_RATIO:
        reasons.append(f"cost ratio {cost_ratio:.2f}x > {H1_MAX_COST_RATIO:.1f}x")
    return HypothesisVerdict("H1", not reasons, tuple(reasons), {
        "wins": wins, "n": n, "win_rate": round(win_rate, 3),
        "wilson_low": round(lo, 3), "wilson_high": round(hi, 3),
        "crew_cost": round(crew_cost, 4), "sprint_cost": round(sprint_cost, 4),
        "cost_ratio": round(cost_ratio, 2) if math.isfinite(cost_ratio) else None,
    })


def verdict_h2(*, caught: int, seeded: int, disagreements: int, graded: int) -> HypothesisVerdict:
    """H2: an independent reviewer catches ≥50% of planted errors, with run-to-run
    disagreement ≤25%.

    `caught`/`seeded` count planted errors on the majority verdict across runs;
    `disagreements`/`graded` count planted errors whose runs did not all agree. The
    noise bound exists because a reviewer that flips a coin also "catches" half.
    """
    reasons: list[str] = []
    catch_rate = caught / seeded if seeded else 0.0
    lo, hi = wilson_interval(caught, seeded)
    noise = disagreements / graded if graded else 0.0
    if not min_sample_met(seeded):
        reasons.append(f"sample {seeded} < {MIN_PAIRS} seeded errors")
    if catch_rate < H2_MIN_CATCH_RATE:
        reasons.append(f"catch rate {catch_rate:.2f} < {H2_MIN_CATCH_RATE:.2f}")
    if noise > H2_MAX_DISAGREEMENT:
        reasons.append(f"disagreement {noise:.2f} > {H2_MAX_DISAGREEMENT:.2f}")
    return HypothesisVerdict("H2", not reasons, tuple(reasons), {
        "caught": caught, "seeded": seeded, "catch_rate": round(catch_rate, 3),
        "wilson_low": round(lo, 3), "wilson_high": round(hi, 3),
        "disagreements": disagreements, "graded": graded, "disagreement": round(noise, 3),
    })


def verdict_h3(*, wins: int, losses: int, n: int, crew_cost: float,
               sprint_cost: float) -> HypothesisVerdict:
    """H3: cheap specialists under a strong coordinator cost ≤70% of a sprint at equal
    judged quality.

    "Equal quality" is read as: the crew did not lose more pairs than it won. Ties
    count for the crew here, unlike H1, because H3 claims parity, not superiority.
    """
    reasons: list[str] = []
    not_worse = wins + (n - wins - losses)
    lo, hi = wilson_interval(not_worse, n)
    cost_ratio = _ratio(crew_cost, sprint_cost)
    if not min_sample_met(n):
        reasons.append(f"sample {n} < {MIN_PAIRS} pairs")
    if losses > wins:
        reasons.append(f"lost {losses} > won {wins}")
    if cost_ratio > H3_MAX_COST_RATIO:
        reasons.append(f"cost ratio {cost_ratio:.2f}x > {H3_MAX_COST_RATIO:.2f}x")
    return HypothesisVerdict("H3", not reasons, tuple(reasons), {
        "wins": wins, "losses": losses, "ties": n - wins - losses, "n": n,
        "wilson_low": round(lo, 3), "wilson_high": round(hi, 3),
        "crew_cost": round(crew_cost, 4), "sprint_cost": round(sprint_cost, 4),
        "cost_ratio": round(cost_ratio, 2) if math.isfinite(cost_ratio) else None,
    })


_VERDICTS = {"H1": verdict_h1, "H2": verdict_h2, "H3": verdict_h3}


def verdict(hypothesis: str, **tallies) -> HypothesisVerdict:
    """Dispatch to the hypothesis' own rule by name ("H1", "H2", "H3")."""
    try:
        rule = _VERDICTS[hypothesis.upper()]
    except KeyError:
        raise ValueError(f"unknown hypothesis {hypothesis!r}; expected one of H1, H2, H3") from None
    return rule(**tallies)
