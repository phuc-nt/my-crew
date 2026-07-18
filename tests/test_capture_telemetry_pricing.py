"""Cost estimation from a per-model price table + summing token usage across messages.

Covers the honest-degrade contract: an unpriced model or missing token counts yield None
(never a fabricated cost), and usage is summed across ALL messages in a multi-turn run.
"""

from __future__ import annotations

from my_crew.llm.model_pricing import estimate_cost, load_prices
from my_crew.runtime.step_telemetry import StepTelemetry, sum_usage_metadata

_PRICES = {
    "minimax/minimax-m2.7": {"input_per_1m": 0.30, "output_per_1m": 1.20},
    "qwen/qwen3.7-max": {"input_per_1m": 0.80, "output_per_1m": 2.40},
}


def test_estimate_cost_priced_model():
    # 1000 in × 0.30/1M + 2000 out × 1.20/1M = 0.0003 + 0.0024 = 0.0027
    cost = estimate_cost("minimax/minimax-m2.7", 1000, 2000, prices=_PRICES)
    assert abs(cost - 0.0027) < 1e-9


def test_estimate_cost_unpriced_model_is_none():
    assert estimate_cost("unknown/model", 1000, 2000, prices=_PRICES) is None


def test_estimate_cost_missing_tokens_is_none():
    assert estimate_cost("minimax/minimax-m2.7", None, None, prices=_PRICES) is None
    assert estimate_cost("minimax/minimax-m2.7", 100, None, prices=_PRICES) is None


def test_estimate_cost_bad_prices_degrade_to_none():
    # A malformed price (non-numeric, negative, NaN, inf) must yield None — never raise, never a
    # negative/NaN cost that would bypass a budget-cap comparison.
    for bad in ("abc", -1.0, float("nan"), float("inf")):
        prices = {"m": {"input_per_1m": bad, "output_per_1m": 1.0}}
        assert estimate_cost("m", 1000, 2000, prices=prices) is None
        prices2 = {"m": {"input_per_1m": 1.0, "output_per_1m": bad}}
        assert estimate_cost("m", 1000, 2000, prices=prices2) is None


def test_load_prices_seed_has_demo_models():
    # The shipped config seeds the two models the demo + default use, so estimated cost is
    # available for them out of the box (values are operator-verifiable placeholders).
    prices = load_prices()
    assert "minimax/minimax-m2.7" in prices
    assert "qwen/qwen3.7-max" in prices


def test_load_prices_missing_file_degrades_to_empty(tmp_path):
    assert load_prices(tmp_path / "nope.yaml") == {}


class _Msg:
    def __init__(self, input_tokens, output_tokens):
        self.usage_metadata = {"input_tokens": input_tokens, "output_tokens": output_tokens}


def test_sum_usage_across_multiple_messages():
    # A multi-turn tool-calling run has many AIMessages; tokens sum across all of them.
    total_in, total_out = sum_usage_metadata([_Msg(10, 20), _Msg(5, 7), _Msg(1, 2)])
    assert total_in == 16 and total_out == 29


def test_sum_usage_no_metadata_is_none():
    # A model that omits usage metadata → (None, None), so cost stays unpriced not zero.
    assert sum_usage_metadata([object(), object()]) == (None, None)


def test_step_telemetry_records_fields():
    t = StepTelemetry()
    t.record(input_tokens=100, output_tokens=50, cost_source="estimated")
    assert t.input_tokens == 100 and t.output_tokens == 50 and t.cost_source == "estimated"
