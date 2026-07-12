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

from pathlib import Path
from typing import Any

from src.config.settings import REPO_ROOT

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
    input_per_1m = entry.get("input_per_1m")
    output_per_1m = entry.get("output_per_1m")
    if input_per_1m is None or output_per_1m is None:
        return None
    return (input_tokens / 1_000_000) * float(input_per_1m) + (
        output_tokens / 1_000_000
    ) * float(output_per_1m)
