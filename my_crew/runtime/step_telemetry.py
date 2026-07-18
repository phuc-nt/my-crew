"""Side-channel telemetry collector for one team-step attempt.

The `run_work` contract is a hard 2-tuple `(result_text, cost_usd)` used across all three
runtime engines and the surrounding team-step graph nodes. It cannot grow extra return
values without a ripple through every runtime. So the extra per-attempt telemetry a work
loop learns — token counts and whether the cost is exact or estimated — rides a mutable
collector passed alongside the call (mirroring the existing search-hook pattern): the caller
creates one, hands it into the work loop, the loop fills it, and the capture layer reads it
after the step returns.

All fields default to None = "the loop did not / could not fill it" (model without usage
metadata, or a caller that never wired a collector). Cost itself is NOT stored here — it
stays on the tuple so there is one source of truth for cost; this object only carries the
token counts and the cost provenance label.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


def sum_usage_metadata(messages: Iterable[Any]) -> tuple[int | None, int | None]:
    """Sum input/output tokens across every message carrying LangChain usage metadata.

    A react/deep-agent run is multi-turn: the result holds many AIMessages (one per tool
    round), each with its own `usage_metadata` (a dict `{input_tokens, output_tokens, ...}`).
    The step's true token count is the sum across all of them, not just the last message.

    Returns (None, None) when NO message carries usage metadata (some models via OpenRouter
    omit it) — the caller then leaves cost unpriced rather than reporting zero.
    """
    total_in = 0
    total_out = 0
    saw_any = False
    for msg in messages:
        usage = getattr(msg, "usage_metadata", None)
        if not isinstance(usage, dict):
            continue
        in_tok = usage.get("input_tokens")
        out_tok = usage.get("output_tokens")
        if in_tok is None and out_tok is None:
            continue
        saw_any = True
        total_in += int(in_tok or 0)
        total_out += int(out_tok or 0)
    if not saw_any:
        return None, None
    return total_in, total_out


@dataclass
class StepTelemetry:
    """Per-attempt token counts + cost provenance, filled by whichever engine ran the step."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    #: "exact" (real provider usage cost, native path) | "estimated" (token × price table,
    #: the langchain engines) | None (not filled).
    cost_source: str | None = None

    def record(
        self,
        *,
        input_tokens: int | None,
        output_tokens: int | None,
        cost_source: str | None,
    ) -> None:
        """Store the token counts + provenance the work loop observed for this attempt."""
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost_source = cost_source
