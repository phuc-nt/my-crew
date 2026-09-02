"""v44 W3: LlmClient transient-error retry — exponential + jitter + Retry-After + total cap.

The retry must de-sync concurrent agents (jitter), obey a server Retry-After when present, and
NEVER let its cumulative wait overrun the sandbox lease (a soft 429 must not become a hard kill).
These tests drive the pure helpers + the retry loop with a monkeypatched sleep (capturing waits),
so no network/key is needed.
"""

from __future__ import annotations

import pytest

from my_crew.llm import client as c
from tests.chat_stream_fakes import fake_stream


class _Headers:
    def __init__(self, mapping):
        self._m = mapping

    def get(self, k, default=None):
        return self._m.get(k, default)


class _Resp:
    def __init__(self, headers):
        self.headers = _Headers(headers)


def _rate_limit(headers=None):
    """A RateLimitError-shaped exc carrying an optional Retry-After header."""
    exc = c.RateLimitError.__new__(c.RateLimitError)  # bypass SDK __init__ (needs httpx.Response)
    exc.response = _Resp(headers or {})
    return exc


def _timeout():
    return c.APITimeoutError.__new__(c.APITimeoutError)  # no .response


# --- _retry_after_seconds ---------------------------------------------------------------

def test_retry_after_parsed_when_present():
    assert c._retry_after_seconds(_rate_limit({"retry-after": "5"})) == 5.0


def test_retry_after_none_without_header():
    assert c._retry_after_seconds(_rate_limit({})) is None


def test_retry_after_none_on_timeout_exc():
    assert c._retry_after_seconds(_timeout()) is None  # no .response attr


def test_retry_after_http_date_degrades_to_none():
    exc = _rate_limit({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
    assert c._retry_after_seconds(exc) is None


def test_retry_after_negative_ignored():
    assert c._retry_after_seconds(_rate_limit({"retry-after": "-3"})) is None


# --- _next_retry_wait -------------------------------------------------------------------

def test_wait_is_exponential_pre_jitter(monkeypatch):
    monkeypatch.setattr(c.random, "uniform", lambda a, b: 1.0)  # kill jitter → base
    w0 = c._next_retry_wait(0, _timeout())
    w1 = c._next_retry_wait(1, _timeout())
    w2 = c._next_retry_wait(2, _timeout())
    assert w0 < w1 < w2  # 1.5, 3.0, 6.0
    assert w0 == pytest.approx(1.5) and w1 == pytest.approx(3.0) and w2 == pytest.approx(6.0)


def test_wait_jitter_within_floor_and_base(monkeypatch):
    seen = {}

    def _fake_uniform(a, b):
        seen["range"] = (a, b)
        return a

    monkeypatch.setattr(c.random, "uniform", _fake_uniform)
    c._next_retry_wait(0, _timeout())
    assert seen["range"] == (c._RETRY_JITTER_FLOOR, 1.0)  # full jitter range


def test_wait_honors_retry_after(monkeypatch):
    monkeypatch.setattr(c.random, "uniform", lambda a, b: 1.0)
    # Retry-After 5 beats exp (attempt 0 exp = 1.5)
    assert c._next_retry_wait(0, _rate_limit({"retry-after": "5"})) == pytest.approx(5.0)


def test_wait_clamps_hostile_retry_after(monkeypatch):
    monkeypatch.setattr(c.random, "uniform", lambda a, b: 1.0)
    assert c._next_retry_wait(0, _rate_limit({"retry-after": "99999"})) == pytest.approx(
        c._RETRY_BACKOFF_CAP_S
    )


def test_wait_clamps_exp_to_cap(monkeypatch):
    monkeypatch.setattr(c.random, "uniform", lambda a, b: 1.0)
    # attempt 10 exp = 1.5*1024 ≫ cap → clamped
    assert c._next_retry_wait(10, _timeout()) == pytest.approx(c._RETRY_BACKOFF_CAP_S)


# --- _call_with_retry loop --------------------------------------------------------------

def _client():
    from my_crew.config.config_builders import build_settings_from_dict

    s = build_settings_from_dict({"openrouter_api_key": "k", "openrouter_model": "x/y"})
    return c.LlmClient(s)


def test_retries_then_raises_after_budget(monkeypatch):
    slept = []
    monkeypatch.setattr(c.time, "sleep", lambda w: slept.append(w))
    monkeypatch.setattr(c.random, "uniform", lambda a, b: 1.0)  # deterministic

    cl = _client()

    calls = {"n": 0}

    class _Boom:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    calls["n"] += 1
                    raise _timeout()

    monkeypatch.setattr(cl, "_client_for", lambda _p: _Boom())
    with pytest.raises(c.ProviderCallError):
        cl._call_with_retry([{"role": "user", "content": "hi"}], "x/y")
    # _MAX_RETRIES=4 → 5 total attempts; 4 sleeps between them
    assert calls["n"] == c._MAX_RETRIES + 1
    assert len(slept) == c._MAX_RETRIES
    assert sum(slept) <= c._RETRY_TOTAL_CAP_S  # total-wait budget respected


def test_total_wait_cap_stops_early(monkeypatch):
    """If waits would exceed the total cap, the loop gives up before oversleeping the lease."""
    slept = []
    monkeypatch.setattr(c.time, "sleep", lambda w: slept.append(w))
    # Force each wait near the per-attempt cap so a few exhaust the total budget.
    monkeypatch.setattr(c, "_next_retry_wait", lambda attempt, exc: c._RETRY_BACKOFF_CAP_S)

    cl = _client()

    class _Boom:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    raise _timeout()

    monkeypatch.setattr(cl, "_client_for", lambda _p: _Boom())
    with pytest.raises(c.ProviderCallError):
        cl._call_with_retry([{"role": "user", "content": "hi"}], "x/y")
    assert sum(slept) <= c._RETRY_TOTAL_CAP_S  # never overran the budget


def test_malformed_body_retries_then_wraps(monkeypatch):
    """A 200-with-garbage body (raw json.JSONDecodeError from the SDK) is a transient
    provider fault: it must retry and, on exhaustion, surface as ProviderCallError so
    the model-chain fallback can advance instead of the whole step dying."""
    slept = []
    monkeypatch.setattr(c.time, "sleep", lambda w: slept.append(w))
    monkeypatch.setattr(c.random, "uniform", lambda a, b: 1.0)
    cl = _client()

    calls = {"n": 0}

    class _Garbage:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    calls["n"] += 1
                    c.json.loads("<html>bad gateway</html>")

    monkeypatch.setattr(cl, "_client_for", lambda _p: _Garbage())
    with pytest.raises(c.ProviderCallError):
        cl._call_with_retry([{"role": "user", "content": "hi"}], "x/y")
    assert calls["n"] == c._MAX_RETRIES + 1


def test_success_on_retry_returns(monkeypatch):
    monkeypatch.setattr(c.time, "sleep", lambda w: None)
    monkeypatch.setattr(c.random, "uniform", lambda a, b: 1.0)
    cl = _client()

    state = {"n": 0}

    class _Flaky:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    state["n"] += 1
                    if state["n"] < 2:
                        raise _timeout()
                    return fake_stream("OK")

    monkeypatch.setattr(cl, "_client_for", lambda _p: _Flaky())
    result = cl._call_with_retry([{"role": "user", "content": "hi"}], "x/y")
    assert result.choices[0].message.content == "OK"
    assert state["n"] == 2  # failed once, succeeded on retry


# --- streamed answers, idle deadline, stall cap ----------------------------------------

def test_a_streamed_answer_is_reassembled_with_finish_reason_usage_and_cost(monkeypatch):
    """Every call streams; what the rest of the client reads is the SDK's reassembled
    completion — content joined across deltas, `finish_reason`, and the trailing usage
    chunk with OpenRouter's `cost` still attached for `extract_usage`."""
    from my_crew.llm.cost import extract_usage

    cl = _client()
    seen = {}

    class _Streaming:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    seen.update(kw)
                    return fake_stream("one two three", cost=0.0042)

    monkeypatch.setattr(cl, "_client_for", lambda _p: _Streaming())
    result = cl._call_with_retry([{"role": "user", "content": "hi"}], "x/y")

    assert seen["stream"] is True
    assert seen["stream_options"] == {"include_usage": True}
    assert result.choices[0].message.content == "one two three"
    assert result.choices[0].finish_reason == "stop"
    usage = extract_usage(result)
    assert usage.prompt_tokens == 10 and usage.completion_tokens == 5
    assert usage.cost_usd == pytest.approx(0.0042)


def test_a_streamed_tool_call_is_reassembled_across_deltas(monkeypatch):
    """Tool arguments arrive in pieces keyed by index; the tool-calling path reads the
    assembled `message.tool_calls`, so a split must land as one call with whole JSON."""
    cl = _client()

    class _ToolStream:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    return fake_stream(tool_call=("web_search", '{"q": "giá xe điện"}'))

    monkeypatch.setattr(cl, "_client_for", lambda _p: _ToolStream())
    result = cl._call_with_retry(
        [{"role": "user", "content": "hi"}],
        "x/y",
        tools=[{"type": "function", "function": {"name": "web_search"}}],
    )

    (call,) = result.choices[0].message.tool_calls
    assert call.id == "call_1"
    assert call.function.name == "web_search"
    assert call.function.arguments == '{"q": "giá xe điện"}'
    assert result.choices[0].finish_reason == "tool_calls"


def test_a_slow_but_progressing_stream_is_never_abandoned(monkeypatch):
    """The bound is idle time, not wall-clock: a model answering at a crawl keeps
    touching progress with every chunk, so a stream far longer than the idle ceiling
    still completes. Measured live, a legitimate review ran 190s at ~23 tokens/s — the
    wall-clock ceiling this replaced would have killed it."""
    monkeypatch.setattr(c, "_STREAM_IDLE_S", 0.2)
    cl = _client()

    def _crawl():
        for chunk in fake_stream("slow answer", cost=0.001):
            c.time.sleep(0.08)  # each gap well inside the idle ceiling…
            yield chunk  # …while the whole stream (~0.5s) runs past it

    class _Crawling:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    return _crawl()

    monkeypatch.setattr(cl, "_client_for", lambda _p: _Crawling())
    result = cl._call_with_retry([{"role": "user", "content": "hi"}], "x/y")
    assert result.choices[0].message.content == "slow answer"


def _stalled_sdk(calls: dict, release):
    """A provider that connects and then sends nothing — the keep-alive-only socket the
    SDK's per-read timeout never catches."""

    class _Stalled:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    calls["n"] += 1
                    release.wait(5)
                    return fake_stream("too late")

    return _Stalled()


def test_a_silent_stream_is_abandoned_and_retried(monkeypatch):
    """OpenRouter keeps a stalled socket busy with keep-alive bytes, so the SDK's
    per-read timeout never fires; measured live, one decompose sat past 900s that way.
    The idle deadline is the bound that does fire: the attempt is abandoned on its
    worker thread, counted as transient, and the loop moves on."""
    import threading

    slept = []
    monkeypatch.setattr(c.time, "sleep", lambda w: slept.append(w))
    monkeypatch.setattr(c.random, "uniform", lambda a, b: 1.0)
    monkeypatch.setattr(c, "_STREAM_IDLE_S", 0.05)
    cl = _client()
    release = threading.Event()
    calls = {"n": 0}
    monkeypatch.setattr(cl, "_client_for", lambda _p: _stalled_sdk(calls, release))
    started = c.time.monotonic()
    try:
        with pytest.raises(c.ProviderCallError) as info:
            cl._call_with_retry([{"role": "user", "content": "hi"}], "x/y")
    finally:
        release.set()  # let the abandoned workers exit instead of outliving the test
    assert "silent for" in str(info.value)
    assert calls["n"] >= 2  # abandoned once, retried at least once
    # The caller was never held for the provider's 5s "stall" — the point of the bound.
    assert c.time.monotonic() - started < 2.0


def test_two_silent_attempts_in_a_row_give_the_model_up_early(monkeypatch):
    """One stall is a blip; a second in a row is the provider. Burning all five attempts
    on silence would hold a step for 5×`_STREAM_IDLE_S` before the chain could advance,
    so the loop stops at `_MAX_STALLED_ATTEMPTS` and raises for the chain instead."""
    import threading

    monkeypatch.setattr(c.time, "sleep", lambda w: None)
    monkeypatch.setattr(c, "_STREAM_IDLE_S", 0.05)
    cl = _client()
    release = threading.Event()
    calls = {"n": 0}
    monkeypatch.setattr(cl, "_client_for", lambda _p: _stalled_sdk(calls, release))
    try:
        with pytest.raises(c.ProviderCallError):
            cl._call_with_retry([{"role": "user", "content": "hi"}], "x/y")
    finally:
        release.set()
    assert calls["n"] == c._MAX_STALLED_ATTEMPTS
    assert c._MAX_STALLED_ATTEMPTS < c._MAX_RETRIES + 1  # the cap is the point


def test_a_stall_followed_by_an_answer_recovers(monkeypatch):
    """The stall counter is consecutive: a blip that clears on the next attempt returns
    that attempt's answer, and a later timeout resets the count."""
    import threading

    monkeypatch.setattr(c.time, "sleep", lambda w: None)
    monkeypatch.setattr(c, "_STREAM_IDLE_S", 0.05)
    cl = _client()
    release = threading.Event()
    calls = {"n": 0}

    class _StallThenAnswer:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    calls["n"] += 1
                    if calls["n"] == 1:
                        release.wait(5)
                    return fake_stream("recovered")

    monkeypatch.setattr(cl, "_client_for", lambda _p: _StallThenAnswer())
    try:
        result = cl._call_with_retry([{"role": "user", "content": "hi"}], "x/y")
    finally:
        release.set()
    assert result.choices[0].message.content == "recovered"
    assert calls["n"] == 2


def test_a_non_transient_error_inside_the_idle_thread_propagates_unchanged(monkeypatch):
    """The worker thread must not launder exception types: a caller bug (or a 4xx the
    SDK raises as a non-retryable error) still surfaces as itself, not as a stall."""
    monkeypatch.setattr(c, "_STREAM_IDLE_S", 5.0)
    cl = _client()

    class _Bug:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    raise ValueError("bad request shape")

    monkeypatch.setattr(cl, "_client_for", lambda _p: _Bug())
    with pytest.raises(ValueError, match="bad request shape"):
        cl._call_with_retry([{"role": "user", "content": "hi"}], "x/y")
