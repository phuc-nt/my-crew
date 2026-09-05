"""Extract token usage + cost from an OpenRouter chat completion.

OpenRouter is OpenAI-compatible but adds a non-standard `cost` field (USD) that
the OpenAI SDK exposes via `model_extra`. It is not guaranteed for every model,
so extraction is tolerant: a missing/garbled cost returns None (cost unknown)
rather than raising. The budget tracker treats unknown cost conservatively.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UsageInfo:
    """Normalized usage from one completion. `cost_usd` is None when unknown."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float | None
    #: Thinking tokens inside `completion_tokens` (OpenRouter's
    #: `completion_tokens_details.reasoning_tokens`); 0 when the provider does not say.
    #: Billed as output, so a step whose visible answer is short but whose
    #: `completion_tokens` is huge is explained here, not in the prompt.
    reasoning_tokens: int = 0


def _get(obj: Any, key: str) -> Any:
    """Read `key` from a pydantic-ish object or a plain dict, else None."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _extra(obj: Any) -> dict[str, Any]:
    """Return provider extra fields (OpenAI SDK `model_extra`) as a dict."""
    if obj is None:
        return {}
    extra = getattr(obj, "model_extra", None)
    if isinstance(extra, dict):
        return extra
    if isinstance(obj, dict):
        return obj
    return {}


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_cost(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_usage(response: Any) -> UsageInfo:
    """Pull token counts + cost from a chat completion response.

    Accepts the OpenAI SDK `ChatCompletion` object or an equivalent dict
    (used in tests). Cost is read from `usage.cost` first, then the top-level
    `cost` field; either may be absent.
    """
    usage = _get(response, "usage")
    prompt_tokens = _coerce_int(_get(usage, "prompt_tokens"))
    completion_tokens = _coerce_int(_get(usage, "completion_tokens"))
    total_tokens = _coerce_int(_get(usage, "total_tokens")) or (
        prompt_tokens + completion_tokens
    )

    # OpenRouter may report cost on usage or at the top level, via model_extra.
    cost = _coerce_cost(_extra(usage).get("cost"))
    if cost is None:
        cost = _coerce_cost(_extra(response).get("cost"))

    details = _get(usage, "completion_tokens_details")
    reasoning_tokens = _coerce_int(_get(details, "reasoning_tokens"))

    return UsageInfo(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cost_usd=cost,
        reasoning_tokens=reasoning_tokens,
    )
