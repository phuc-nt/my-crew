"""OpenRouter chat client (provider-agnostic at the call site).

Uses the raw `openai` SDK pointed at OpenRouter's base URL rather than
LangChain's ChatOpenAI, because ChatOpenAI drops OpenRouter's non-standard
`cost`/usage extras that the budget tracker needs.

Every call is budget-gated (before) and cost-recorded (after), and is bounded:
a request timeout plus a small bounded retry on transient errors, so a hung
provider cannot stall the agent (code-standards.md §6). With a v4 M9 model_chain
the bound is per-model (~3×60s each), so worst case scales by chain length —
keep chains short (2-3 models).
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

from my_crew.config.settings import OPENROUTER_BASE_URL, Settings
from my_crew.llm.budget_tracker import BudgetTracker
from my_crew.llm.cost import extract_usage
from my_crew.llm.fallback_policy import ProviderCallError, should_try_next_model

logger = logging.getLogger(__name__)

# Bounded I/O: per-request timeout and a bounded retry budget for transient faults.
_REQUEST_TIMEOUT_S = 60.0
# v44: exponential backoff + full jitter + honor Retry-After, up to 4 retries. Under a team run
# (many agents on one OpenRouter upstream) linear un-jittered retries fire in lockstep → a
# self-inflicted 429 storm; jitter de-syncs them. TOTAL retry wall-time is capped WELL under the
# sandbox lease (SANDBOX_LEASE_S=1800) so a retry stall inside a deep_agent step can never overrun
# the lease and turn a soft 429 into a hard SIGKILL — this cap is the load-bearing safety bound.
_MAX_RETRIES = 4
_RETRY_BACKOFF_S = 1.5  # base for exp: 1.5 · 2^attempt (pre-jitter)
_RETRY_BACKOFF_CAP_S = 30.0  # per-attempt ceiling (also clamps a hostile Retry-After)
_RETRY_TOTAL_CAP_S = 75.0  # sum ceiling across all attempts — ≪ 1800s lease
_RETRY_JITTER_FLOOR = 0.5  # jitter multiplier floor so a wait never collapses to ~0
_RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError)

Message = dict[str, str]


def _retry_after_seconds(exc: Exception) -> float | None:
    """Seconds from a `Retry-After` header if the error carries one, else None.

    Only `APIStatusError` subclasses (e.g. `RateLimitError` on a 429) have a `.response`;
    `APITimeoutError`/`APIConnectionError` do not. `Retry-After` is usually an int (seconds) on
    OpenRouter; an HTTP-date form (or anything unparseable) degrades to None so the caller falls
    back to exponential backoff — never crash the retry path over a header quirk.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        secs = float(str(raw).strip())
    except (TypeError, ValueError):
        return None  # HTTP-date or garbage → fall back to exp backoff
    return secs if secs >= 0 else None


def _next_retry_wait(attempt: int, exc: Exception) -> float:
    """The jittered wait before the next retry.

    Base is a server `Retry-After` when present, else exponential `1.5 · 2^attempt`; either is
    clamped to `_RETRY_BACKOFF_CAP_S` (so a hostile/huge Retry-After can't stall us), then full
    jitter in `[_RETRY_JITTER_FLOOR, 1.0] · base` de-syncs concurrent agents' retries.
    """
    server = _retry_after_seconds(exc)
    base = server if server is not None else _RETRY_BACKOFF_S * (2 ** attempt)
    base = min(base, _RETRY_BACKOFF_CAP_S)
    return base * random.uniform(_RETRY_JITTER_FLOOR, 1.0)


@dataclass(frozen=True)
class LlmResult:
    """One completion's content plus accounting.

    `model` is the model that ACTUALLY answered; `fallback_from` lists the chain
    entries that failed before it (empty on the normal primary-model path), so a
    caller/operator can always see a completion was served by a fallback.
    """

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None
    fallback_from: tuple[str, ...] = ()


class LlmClient:
    """Thin OpenRouter wrapper with budget gating and usage accounting."""

    def __init__(
        self,
        settings: Settings,
        budget: BudgetTracker | None = None,
    ) -> None:
        self._settings = settings
        self._budget = budget or BudgetTracker(self._settings)
        self._client: OpenAI | None = None

    def _openai(self) -> OpenAI:
        """Lazily build the SDK client so non-LLM code needs no API key."""
        if self._client is None:
            self._client = OpenAI(
                base_url=OPENROUTER_BASE_URL,
                api_key=self._settings.require_api_key(),
                timeout=_REQUEST_TIMEOUT_S,
            )
        return self._client

    def complete(self, messages: list[Message], *, model: str | None = None) -> LlmResult:
        """Run one chat completion, walking the model chain on provider failure (v4 M9).

        An explicit `model=` bypasses the chain (single model, pre-v4 behavior); so
        does an undeclared chain (`effective_model_chain()` is then one entry). The
        budget cap is re-checked before EVERY attempt — a fallback can never spend
        past it — and the cost of every completed attempt is recorded. Every fallback
        is logged loudly (a completion silently served by a lesser model is how bad
        prose sneaks into reports unnoticed — M9 risk R1).

        Raises BudgetExceededError if the monthly cap is hit, or the last model's
        error when the whole chain is exhausted.
        """
        chain = (model,) if model else self._settings.effective_model_chain()
        if not model and len(chain) > 1 and chain[0] != self._settings.openrouter_model:
            # A declared chain overrides `model:` entirely — say so once per call, or a
            # stale OPENROUTER_MODEL_CHAIN env can silently serve an old model forever.
            logger.warning(
                "model_chain %s overrides configured model %r (chain[0] serves)",
                list(chain), self._settings.openrouter_model,
            )
        fallback_from: list[str] = []

        for i, model_name in enumerate(chain):
            self._budget.check_allowed()  # supreme: re-checked before every attempt
            has_next = i < len(chain) - 1
            try:
                response = self._call_with_retry(messages, model_name)
            except Exception as exc:
                if has_next and should_try_next_model(exc):
                    logger.warning(
                        "FALLBACK: model %r failed (%s: %s); trying %r",
                        model_name, type(exc).__name__, exc, chain[i + 1],
                    )
                    fallback_from.append(model_name)
                    continue
                raise

            usage = extract_usage(response)
            self._budget.record_cost(usage.cost_usd)  # every billed attempt counts
            content = response.choices[0].message.content or ""
            if not content.strip() and has_next:
                logger.warning(
                    "FALLBACK: model %r returned empty content; trying %r",
                    model_name, chain[i + 1],
                )
                fallback_from.append(model_name)
                continue
            if fallback_from:
                logger.warning(
                    "FALLBACK: completion served by %r after %s failed",
                    model_name, fallback_from,
                )
            return LlmResult(
                content=content,
                model=model_name,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                cost_usd=usage.cost_usd,
                fallback_from=tuple(fallback_from),
            )

        # Unreachable: the chain is never empty and its LAST entry either returns a
        # result or re-raises (has_next=False) — exhaustion = the last model's raw error.
        raise AssertionError("unreachable: model chain loop always returns or raises")

    def _call_with_retry(self, messages: list[Message], model_name: str):
        """Call the API, retrying bounded times on transient errors only.

        v44: exponential backoff with full jitter, honoring a server `Retry-After` when present,
        and a TOTAL retry-wait budget (`_RETRY_TOTAL_CAP_S`) so a stall can never overrun the
        sandbox lease. Only transient errors (`_RETRYABLE`) retry; everything else propagates.
        """
        headers = {
            "HTTP-Referer": self._settings.openrouter_referer,
            "X-Title": self._settings.openrouter_title,
        }
        last_exc: Exception | None = None
        total_slept = 0.0
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return self._openai().chat.completions.create(
                    model=model_name,
                    messages=messages,
                    extra_headers=headers,
                )
            except _RETRYABLE as exc:
                last_exc = exc
                if attempt == _MAX_RETRIES:
                    break
                wait = _next_retry_wait(attempt, exc)
                # Total-wait budget: if this sleep would exceed the cap, stop retrying now rather
                # than risk overrunning the lease (a soft 429 must never become a hard SIGKILL).
                if total_slept + wait > _RETRY_TOTAL_CAP_S:
                    logger.warning(
                        "OpenRouter transient error (attempt %d/%d): %s; retry budget "
                        "(%.0fs) exhausted, giving up",
                        attempt + 1, _MAX_RETRIES + 1, exc, _RETRY_TOTAL_CAP_S,
                    )
                    break
                logger.warning(
                    "OpenRouter transient error (attempt %d/%d): %s; retrying in %.1fs",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    exc,
                    wait,
                )
                time.sleep(wait)
                total_slept += wait
        # Explicit error with context, never swallowed (code-standards.md §5).
        # ProviderCallError (not bare RuntimeError) so the fallback policy can tell
        # "this model is exhausted" apart from unrelated RuntimeErrors (missing key).
        raise ProviderCallError(
            f"OpenRouter call failed after {_MAX_RETRIES + 1} attempts for model "
            f"{model_name!r}: {last_exc}"
        ) from last_exc
