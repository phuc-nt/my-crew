"""OpenRouter chat client (provider-agnostic at the call site).

Uses the raw `openai` SDK pointed at OpenRouter's base URL rather than
LangChain's ChatOpenAI, because ChatOpenAI drops OpenRouter's non-standard
`cost`/usage extras that the budget tracker needs.

Every call is budget-gated (before) and cost-recorded (after), and is bounded:
a request timeout plus a small bounded retry on transient errors, so a hung
provider cannot stall the agent (code-standards.md §6).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

from src.config.settings import OPENROUTER_BASE_URL, Settings, get_settings
from src.llm.budget_tracker import BudgetTracker
from src.llm.cost import extract_usage

logger = logging.getLogger(__name__)

# Bounded I/O: per-request timeout and a small retry budget for transient faults.
_REQUEST_TIMEOUT_S = 60.0
_MAX_RETRIES = 2
_RETRY_BACKOFF_S = 1.5
_RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError)

Message = dict[str, str]


@dataclass(frozen=True)
class LlmResult:
    """One completion's content plus accounting."""

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None


class LlmClient:
    """Thin OpenRouter wrapper with budget gating and usage accounting."""

    def __init__(
        self,
        settings: Settings | None = None,
        budget: BudgetTracker | None = None,
    ) -> None:
        self._settings = settings or get_settings()
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
        """Run one chat completion. Budget-checked before, cost-recorded after.

        Raises BudgetExceededError (from the tracker) if the monthly cap is hit,
        or the underlying OpenAI error if the request ultimately fails.
        """
        self._budget.check_allowed()
        model_name = model or self._settings.openrouter_model

        response = self._call_with_retry(messages, model_name)

        usage = extract_usage(response)
        self._budget.record_cost(usage.cost_usd)

        choice = response.choices[0]
        content = choice.message.content or ""
        return LlmResult(
            content=content,
            model=model_name,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cost_usd=usage.cost_usd,
        )

    def _call_with_retry(self, messages: list[Message], model_name: str):
        """Call the API, retrying bounded times on transient errors only."""
        headers = {
            "HTTP-Referer": self._settings.openrouter_referer,
            "X-Title": self._settings.openrouter_title,
        }
        last_exc: Exception | None = None
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
                wait = _RETRY_BACKOFF_S * (attempt + 1)
                logger.warning(
                    "OpenRouter transient error (attempt %d/%d): %s; retrying in %.1fs",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    exc,
                    wait,
                )
                time.sleep(wait)
        # Explicit error with context, never swallowed (code-standards.md §5).
        raise RuntimeError(
            f"OpenRouter call failed after {_MAX_RETRIES + 1} attempts for model "
            f"{model_name!r}: {last_exc}"
        ) from last_exc
