"""Estimate a completion's cost from token counts + a per-model price table.

The native engine reports a real provider cost (OpenRouter usage), but the tool-calling
engines run through LangChain's ChatOpenAI, which does not surface that cost here. For those,
cost is estimated: token counts (summed from the response's usage metadata) times a per-model
price loaded from `config/model_prices.yaml`.

Honest degrade is the rule: a model missing from the table, or missing token counts, yields
None — never a fabricated number. The capture row records `cost_source="estimated"` so a
consumer knows the provenance.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

from my_crew.config.settings import REPO_ROOT

logger = logging.getLogger(__name__)

#: Default location of the price table (repo-root config/), overridable for tests.
DEFAULT_PRICES_PATH = REPO_ROOT / "config" / "model_prices.yaml"


def load_prices(path: Path | None = None) -> dict[str, dict[str, float]]:
    """Load `{model: {input_per_1m, output_per_1m}}` from the YAML table.

    A missing file or malformed shape degrades to `{}` (no prices) rather than raising —
    an absent table must not break step execution, only leave cost unpriced.
    """
    import yaml

    price_path = path or DEFAULT_PRICES_PATH
    if not price_path.exists():
        return {}
    doc = yaml.safe_load(price_path.read_text(encoding="utf-8")) or {}
    models = doc.get("models") if isinstance(doc, dict) else None
    if not isinstance(models, dict):
        return {}
    return models


def estimate_cost(
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    *,
    prices: dict[str, Any] | None = None,
) -> float | None:
    """Return estimated USD cost, or None when the model is unpriced or tokens are missing.

    `prices` may be injected (tests, or a caller that already loaded the table) to avoid a
    file read per call; when omitted the table is loaded from `config/model_prices.yaml`.
    """
    if input_tokens is None or output_tokens is None:
        return None
    table = prices if prices is not None else load_prices()
    entry = table.get(model)
    if not isinstance(entry, dict):
        return None
    in_price = _safe_price(entry.get("input_per_1m"), model, "input_per_1m")
    out_price = _safe_price(entry.get("output_per_1m"), model, "output_per_1m")
    if in_price is None or out_price is None:
        return None
    return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price


def _safe_price(value: Any, model: str, field: str) -> float | None:
    """Coerce a YAML price to a usable non-negative finite float, else None (logged).

    A bad price (non-numeric, negative, NaN, or inf) must degrade to None — never raise, and
    never a negative/NaN cost that would silently poison a budget-cap comparison (`nan > cap` is
    always False, which would let spend through unchecked).
    """
    try:
        price = float(value)
    except (TypeError, ValueError):
        logger.warning("model price %s for %r is not a number (%r) — ignoring", field, model, value)
        return None
    if not math.isfinite(price) or price < 0:
        logger.warning("model price %s for %r is not a finite >=0 value (%r) — ignoring",
                       field, model, price)
        return None
    return price
