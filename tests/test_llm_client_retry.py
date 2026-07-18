"""v44 W3: LlmClient transient-error retry — exponential + jitter + Retry-After + total cap.

The retry must de-sync concurrent agents (jitter), obey a server Retry-After when present, and
NEVER let its cumulative wait overrun the sandbox lease (a soft 429 must not become a hard kill).
These tests drive the pure helpers + the retry loop with a monkeypatched sleep (capturing waits),
so no network/key is needed.
"""

from __future__ import annotations

import pytest

from my_crew.llm import client as c


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

    monkeypatch.setattr(cl, "_openai", lambda: _Boom())
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

    monkeypatch.setattr(cl, "_openai", lambda: _Boom())
    with pytest.raises(c.ProviderCallError):
        cl._call_with_retry([{"role": "user", "content": "hi"}], "x/y")
    assert sum(slept) <= c._RETRY_TOTAL_CAP_S  # never overran the budget


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
                    return "OK"

    monkeypatch.setattr(cl, "_openai", lambda: _Flaky())
    assert cl._call_with_retry([{"role": "user", "content": "hi"}], "x/y") == "OK"
    assert state["n"] == 2  # failed once, succeeded on retry
