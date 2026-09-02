"""OpenRouter chat client (provider-agnostic at the call site).

Uses the raw `openai` SDK pointed at OpenRouter's base URL rather than
LangChain's ChatOpenAI, because ChatOpenAI drops OpenRouter's non-standard
`cost`/usage extras that the budget tracker needs.

Every call is budget-gated (before) and cost-recorded (after), and is bounded:
a request timeout, an idle deadline on the streamed answer (`_STREAM_IDLE_S`, because
OpenRouter keeps a stalled socket busy with keep-alive bytes and the read timeout alone
never fires), plus a small bounded retry on transient errors, so a hung provider cannot
stall the agent (code-standards.md §6). With a v4 M9 model_chain the bound is per-model, so
worst case scales by chain length — keep chains short (2-3 models).
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from dataclasses import dataclass
from functools import partial

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError
from openai.lib.streaming.chat import ChatCompletionStreamState

from my_crew.config.settings import OPENROUTER_BASE_URL, Settings
from my_crew.llm.budget_tracker import BudgetTracker
from my_crew.llm.cost import extract_usage
from my_crew.llm.fallback_policy import ProviderCallError, should_try_next_model
from my_crew.runtime.step_recorder import record_event

logger = logging.getLogger(__name__)

# Bounded I/O: per-request timeout and a bounded retry budget for transient faults.
_REQUEST_TIMEOUT_S = 60.0
# Idle ceiling on ONE attempt, enforced from OUTSIDE the SDK call. `_REQUEST_TIMEOUT_S` is
# httpx's per-read timeout and OpenRouter defeats it by design: while an upstream provider
# stalls, it keeps the socket busy with keep-alive bytes (whitespace on a non-streaming
# body, SSE comments on a stream), so the socket never goes quiet. Measured live
# (2026-09-02): one decompose call sat past 900s receiving 23k chars of whitespace before
# the body ended with no JSON at all (`Expecting value: line 4285 column 1`), and the
# synchronous delegate behind it never answered the CEO.
#
# A plain wall-clock ceiling (240s) was tried first and was the wrong bound: the same
# evening the same model answered at ~23 tokens/s, a legitimate 4.5k-token review took
# 190s, and a full decompose could outlive any ceiling short enough to catch a hang. So
# every call STREAMS, and the bound is idle time. The SDK drops keep-alive comments, hence
# a chunk is progress and silence is a stall: a slow answer is never abandoned, a silent
# one is — on its worker thread, after `_STREAM_IDLE_S` without a chunk. Sized above the
# longest silence a healthy call shows (first-token latency on a queued request, or a
# reasoning model thinking before it emits), not for a hang.
_STREAM_IDLE_S = 120.0
# Silent attempts in a row before the model is given up for this call. One is a blip and
# retries like a timeout; a second is the provider, and the chain (or the caller's own
# retry) is a better next move than a third `_STREAM_IDLE_S` of silence.
_MAX_STALLED_ATTEMPTS = 2
# v91 multi-provider: a chain entry may be prefixed `provider::model` to route it at a
# non-OpenRouter OpenAI-compatible endpoint. `::` because OpenRouter ids already spend
# `/` (org/model) and `:` (`:free`-style suffixes); no known model id contains `::`.
_PROVIDER_SEP = "::"
# The implicit provider a bare `org/model` entry resolves through — reserved in
# `config_builders._d_providers` so a registry can never redirect it.
_OPENROUTER = "openrouter"
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
# json.JSONDecodeError: OpenRouter can 200 with a malformed body (proxy truncation, upstream
# hiccup); the SDK lets the raw parse error escape. That is a transient provider fault, not a
# caller bug — retry it, and on exhaustion the ProviderCallError wrapper advances the model chain.
class RequestDeadlineExceeded(Exception):
    """One attempt went `_STREAM_IDLE_S` without a chunk. Transient by construction (the
    provider was still connected, just not answering), so it retries like a timeout and,
    on exhaustion, advances the model chain through `ProviderCallError`."""


_RETRYABLE = (
    APITimeoutError, APIConnectionError, RateLimitError, json.JSONDecodeError,
    RequestDeadlineExceeded,
)


class _Progress:
    """Monotonic time of the last chunk on a streaming call; the idle watchdog in
    `_run_until_idle` measures silence from it."""

    __slots__ = ("at",)

    def __init__(self) -> None:
        self.at = time.monotonic()

    def touch(self) -> None:
        self.at = time.monotonic()


def _run_until_idle(fn, idle_s: float, *, what: str, progress: _Progress):
    """Run `fn()` on a daemon thread and return its result, or raise
    `RequestDeadlineExceeded` once `idle_s` passes with no `progress.touch()`.

    The thread is abandoned, not killed — Python cannot interrupt a blocking socket read —
    so a stalled call keeps its socket until the provider closes it. That is the whole
    trade: a leaked thread per hang, against a step (or the CEO's synchronous delegate)
    waiting an unbounded time for bytes that are not an answer. An exception raised
    inside `fn` is re-raised on the caller's thread unchanged, so the retry loop sees the
    same types it always did."""
    outcome: dict = {}

    def _target() -> None:
        try:
            outcome["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — re-raised on the caller's thread
            outcome["error"] = exc

    worker = threading.Thread(target=_target, name=f"llm-{what}", daemon=True)
    worker.start()
    while True:
        # Wait exactly until the current silence would become a stall, then re-check:
        # a chunk that landed meanwhile pushed the deadline out.
        worker.join(max(idle_s - (time.monotonic() - progress.at), 0.01))
        if not worker.is_alive():
            break
        if time.monotonic() - progress.at >= idle_s:
            raise RequestDeadlineExceeded(
                f"{what} silent for {idle_s:.0f}s — abandoned"
            )
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


def _stream_completion(client, *, progress: _Progress, **request):
    """One chat completion over SSE, reassembled into the SDK's `ChatCompletion` shape.

    Every chunk touches `progress`. The trailing choice-less chunk carries `usage`
    (`include_usage`), which OpenRouter extends with `cost` exactly as it does on a
    non-streaming body — so `extract_usage` reads the result unchanged."""
    state = ChatCompletionStreamState()
    stream = client.chat.completions.create(
        stream=True, stream_options={"include_usage": True}, **request
    )
    for chunk in stream:
        progress.touch()
        state.handle_chunk(chunk)
    return state.get_final_completion()

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


def looks_truncated(content: str) -> bool:
    """True when `content` has the SHAPE of a body that stopped mid-write.

    A conservative fallback for when the provider does not report `finish_reason`.
    "Conservative" is the whole design constraint: a body that is merely malformed in
    some other way must keep taking the JSON-error path, because the two retries ask for
    opposite things — one for a SHORTER plan, one for well-formed JSON — and answering
    the wrong question wastes a paid round.

    So this only reports the one unambiguous signature: text that opened a JSON structure
    and never closed it. Balanced-but-invalid JSON (a trailing comma, a bare key, the
    wrong type) is not truncation and is not reported. Quotes are tracked so a brace
    inside a string value cannot throw off the count, and escapes so a `\\"` inside a
    string does not look like its end.
    """
    text = content.strip()
    if not text or text[0] not in "{[":
        return False  # not a JSON body at all — no shape to judge

    depth = 0
    in_string = False
    escaped = False
    for ch in text:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            if in_string:
                escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
    # An unterminated string, or a structure still open at the end, means the writer
    # stopped mid-way. A negative depth is malformed some OTHER way — not our signal.
    return in_string or depth > 0


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
    #: Why the provider stopped. "length" means the answer is CUT OFF mid-token — the
    #: content is a prefix, not an answer. Callers that parse structured output must
    #: check `truncated` before trusting a parse failure as "the model wrote garbage":
    #: a truncated body fails the same way but for a reason retrying identically will
    #: not fix. Defaults to "" so every existing construction site (tests, doubles)
    #: keeps working and simply reports "not truncated".
    finish_reason: str = ""

    @property
    def truncated(self) -> bool:
        """The answer was cut off by the output-token limit.

        `finish_reason` alone under-reports: a provider that streams, hits a proxy
        timeout, or simply omits the field returns a body cut mid-field with
        `finish_reason=""`. That was measured in production — a decomposition cut mid
        string was read as "the model wrote garbage", so the retry asked for valid JSON
        and got the same too-long plan again. Fall back to the body's SHAPE when the
        provider does not say.
        """
        return self.finish_reason == "length" or (
            self.finish_reason != "stop" and looks_truncated(self.content)
        )


@dataclass(frozen=True)
class ToolExchange:
    """One tool-capable completion: the raw assistant message + accounting.

    `message` is the assistant message as a dict (SDK `model_dump()`), keeping
    `tool_calls` and any provider reasoning fields (`reasoning`/`reasoning_details`)
    intact for verbatim passback — a tool loop needs the wire shape, not just text.
    """

    message: dict
    finish_reason: str
    result: LlmResult


class LlmClient:
    """Thin OpenRouter wrapper with budget gating and usage accounting."""

    def __init__(
        self,
        settings: Settings,
        budget: BudgetTracker | None = None,
    ) -> None:
        self._settings = settings
        self._budget = budget or BudgetTracker(self._settings)
        # One SDK client per provider, built on first use. Keyed by the provider name
        # (`_OPENROUTER` for a bare entry) so a chain that walks across providers does
        # not rebuild a client — and so a provider whose key is unset only raises when
        # a chain entry actually reaches it, not at construction.
        self._clients: dict[str, OpenAI] = {}

    def _resolve_entry(self, entry: str) -> tuple[str, str]:
        """Split a chain entry into `(provider_name, model_id)`.

        `provider::model` names a registry provider; a bare `org/model` is OpenRouter,
        exactly as pre-v91. Splits on the FIRST `::` only, and the model id sent to the
        API is the part after it — the prefix is routing, not part of the name upstream
        knows.
        """
        provider, sep, model = entry.partition(_PROVIDER_SEP)
        if not sep:
            return _OPENROUTER, entry
        if not provider or not model:
            raise ValueError(
                f"model entry {entry!r} is malformed — use 'provider::model' "
                "(both halves non-empty), or a bare model id for OpenRouter"
            )
        return provider, model

    def _client_for(self, provider: str) -> OpenAI:
        """Lazily build (and cache) the SDK client for one provider.

        Lazy for the same reason the single client was: non-LLM code (guardrails, graph
        build) must run with no API key configured at all.
        """
        cached = self._clients.get(provider)
        if cached is not None:
            return cached
        if provider == _OPENROUTER:
            base_url = OPENROUTER_BASE_URL
            api_key = self._settings.require_api_key()
        else:
            base_url, _env = self._settings.provider_for(provider)
            api_key = self._settings.require_provider_key(provider)
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=_REQUEST_TIMEOUT_S)
        self._clients[provider] = client
        return client

    def complete(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        role: str | None = None,
    ) -> LlmResult:
        """Run one chat completion, walking the model chain on provider failure (v4 M9).

        An explicit `model=` bypasses the chain (single model, pre-v4 behavior); so
        does an undeclared chain (`effective_model_chain()` is then one entry). The
        budget cap is re-checked before EVERY attempt — a fallback can never spend
        past it — and the cost of every completed attempt is recorded. Every fallback
        is logged loudly (a completion silently served by a lesser model is how bad
        prose sneaks into reports unnoticed — M9 risk R1).

        `role=` names this call's work kind (see `settings.MODEL_ROLES`) and resolves
        through `model_for_role`, which keeps the fleet chain as a fallback tail — so
        naming a role can make a call cheaper but never leaves it without a fallback.
        A role with no configured override is exactly the default chain, which is why
        call sites can declare their role before any override exists. An explicit
        `model=` still wins over `role=`.

        Raises BudgetExceededError if the monthly cap is hit, or the last model's
        error when the whole chain is exhausted.
        """
        if model:
            chain: tuple[str, ...] = (model,)
        elif role:
            chain = self._settings.model_for_role(role)
        else:
            chain = self._settings.effective_model_chain()
        if (
            not model and not role and len(chain) > 1
            and chain[0] != self._settings.openrouter_model
        ):
            # A declared chain overrides `model:` entirely — say so once per call, or a
            # stale OPENROUTER_MODEL_CHAIN env can silently serve an old model forever.
            logger.warning(
                "model_chain %s overrides configured model %r (chain[0] serves)",
                list(chain), self._settings.openrouter_model,
            )
        fallback_from: list[str] = []
        # Step transcript (v80): verbatim request messages — no-op outside a step context.
        record_event({
            "t": "llm_request", "role": role, "chain": list(chain), "messages": messages,
        })

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
            choice = response.choices[0]
            content = choice.message.content or ""
            finish_reason = str(getattr(choice, "finish_reason", "") or "")
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
            record_event({
                "t": "llm_response", "model": model_name, "content": content,
                "finish_reason": finish_reason,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "cost_usd": usage.cost_usd, "fallback_from": list(fallback_from),
            })
            return LlmResult(
                content=content,
                model=model_name,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                cost_usd=usage.cost_usd,
                fallback_from=tuple(fallback_from),
                finish_reason=finish_reason,
            )

        # Unreachable: the chain is never empty and its LAST entry either returns a
        # result or re-raises (has_next=False) — exhaustion = the last model's raw error.
        raise AssertionError("unreachable: model chain loop always returns or raises")

    def complete_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        model: str | None = None,
        role: str | None = None,
    ) -> ToolExchange:
        """One tool-capable completion with the same budget/retry/chain semantics as
        `complete`, returning the raw assistant message + finish_reason.

        Differences from `complete`, both deliberate:
        - the empty-content fallback only fires when the message ALSO has no
          tool_calls — a tool-call turn legitimately carries empty text;
        - the assistant message is returned as a dict (`model_dump()`), preserving
          `tool_calls` and provider reasoning fields for verbatim passback.
        """
        if model:
            chain: tuple[str, ...] = (model,)
        elif role:
            chain = self._settings.model_for_role(role)
        else:
            chain = self._settings.effective_model_chain()
        fallback_from: list[str] = []
        record_event({
            "t": "llm_request", "role": role, "chain": list(chain),
            "tools": [t.get("function", {}).get("name") for t in tools],
            "messages": messages,
        })

        for i, model_name in enumerate(chain):
            self._budget.check_allowed()
            has_next = i < len(chain) - 1
            try:
                response = self._call_with_retry(messages, model_name, tools=tools)
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
            self._budget.record_cost(usage.cost_usd)
            choice = response.choices[0]
            raw_msg = choice.message
            message: dict = (
                raw_msg.model_dump() if hasattr(raw_msg, "model_dump") else dict(raw_msg)
            )
            content = message.get("content") or ""
            tool_calls = message.get("tool_calls") or []
            if not content.strip() and not tool_calls and has_next:
                logger.warning(
                    "FALLBACK: model %r returned empty content and no tool calls; "
                    "trying %r", model_name, chain[i + 1],
                )
                fallback_from.append(model_name)
                continue
            if fallback_from:
                logger.warning(
                    "FALLBACK: completion served by %r after %s failed",
                    model_name, fallback_from,
                )
            finish_reason = str(getattr(choice, "finish_reason", "") or "")
            record_event({
                "t": "llm_response", "model": model_name, "content": content,
                "tool_calls": [
                    {"name": (tc.get("function") or {}).get("name"),
                     "arguments": (tc.get("function") or {}).get("arguments")}
                    for tc in tool_calls
                ],
                "finish_reason": finish_reason,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "cost_usd": usage.cost_usd, "fallback_from": list(fallback_from),
            })
            return ToolExchange(
                message=message,
                finish_reason=finish_reason,
                result=LlmResult(
                    content=content,
                    model=model_name,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    cost_usd=usage.cost_usd,
                    fallback_from=tuple(fallback_from),
                    finish_reason=finish_reason,
                ),
            )

        raise AssertionError("unreachable: model chain loop always returns or raises")

    def _call_with_retry(
        self, messages: list[Message], model_name: str, *, tools: list[dict] | None = None,
    ):
        """Call the API, retrying bounded times on transient errors only.

        v44: exponential backoff with full jitter, honoring a server `Retry-After` when present,
        and a TOTAL retry-wait budget (`_RETRY_TOTAL_CAP_S`) so a stall can never overrun the
        sandbox lease. Only transient errors (`_RETRYABLE`) retry; everything else propagates.
        """
        provider, model_id = self._resolve_entry(model_name)
        # HTTP-Referer/X-Title are OpenRouter's attribution headers. Sending them to
        # another vendor's endpoint is at best ignored and at worst rejected, so they
        # ride only on OpenRouter calls.
        headers = (
            {
                "HTTP-Referer": self._settings.openrouter_referer,
                "X-Title": self._settings.openrouter_title,
            }
            if provider == _OPENROUTER
            else {}
        )
        last_exc: Exception | None = None
        total_slept = 0.0
        extra_kwargs: dict = {"tools": tools} if tools is not None else {}
        client = self._client_for(provider)
        stalled = 0
        for attempt in range(_MAX_RETRIES + 1):
            progress = _Progress()
            try:
                return _run_until_idle(
                    partial(
                        _stream_completion, client, progress=progress, model=model_id,
                        messages=messages, extra_headers=headers, **extra_kwargs,
                    ),
                    _STREAM_IDLE_S,
                    what=f"chat.completions({model_id})",
                    progress=progress,
                )
            except _RETRYABLE as exc:
                last_exc = exc
                if isinstance(exc, RequestDeadlineExceeded):
                    stalled += 1
                    if stalled >= _MAX_STALLED_ATTEMPTS:
                        logger.warning(
                            "OpenRouter transient error (attempt %d/%d): %s; silent %d "
                            "attempts in a row, giving the model up for this call",
                            attempt + 1, _MAX_RETRIES + 1, exc, stalled,
                        )
                        break
                else:
                    stalled = 0
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
