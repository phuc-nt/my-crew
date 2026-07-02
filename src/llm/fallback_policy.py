"""Which LLM-call failure moves to the NEXT model in the chain (v4 M9).

Pure decision table over exception types — no I/O, no retries here (the client owns
per-model transient retries; this decides what happens when a model is exhausted).

Fallback-eligible (the failure is plausibly model/provider-specific or transient):
    402 credit cap · 404/400 unknown-model · 408/429/5xx/529 · timeout · connection
    error · retries-exhausted (`ProviderCallError`).
NEVER fallback (the failure would hit every model in the chain identically):
    `BudgetExceededError` — the budget cap is supreme (PDR §7.8); a fallback must not
    become a way to spend past it.
    401/403 — auth/permission is per-key, not per-model; retrying other models just
    burns wall-clock and hides the misconfiguration.
    Anything else (missing API key RuntimeError, programming errors) — raise loudly.
"""

from __future__ import annotations

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from src.llm.budget_tracker import BudgetExceededError


class ProviderCallError(RuntimeError):
    """A model's call failed after the client's bounded transient retries."""


#: Status codes where trying another model cannot help (key-level, not model-level).
_NO_FALLBACK_STATUS = frozenset({401, 403})


def should_try_next_model(exc: Exception) -> bool:
    """True when the chain should advance to the next model after this failure."""
    if isinstance(exc, BudgetExceededError):
        return False
    if isinstance(exc, APIStatusError):
        return exc.status_code not in _NO_FALLBACK_STATUS
    if isinstance(exc, (APITimeoutError, APIConnectionError, RateLimitError)):
        return True
    return isinstance(exc, ProviderCallError)
