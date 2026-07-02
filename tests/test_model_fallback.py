"""v4 M9: model fallback chain — policy table, chain walk, budget supremacy, config.

Offline: `_call_with_retry` is stubbed per test; no network, no key. Load-bearing
properties:

- No declared chain (or explicit `model=`) ⇒ ONE call, empty `fallback_from` —
  byte-identical pre-v4 behavior.
- Provider failures (402/429/5xx/timeout/retries-exhausted/empty content) advance the
  chain; key-level failures (401/403) and BudgetExceededError NEVER do.
- The budget cap is re-checked before every attempt and the cost of every billed
  attempt is recorded — a fallback cannot spend past the cap.
"""

from __future__ import annotations

import httpx
import pytest
from openai import APIStatusError, APITimeoutError

from src.config.config_builders import build_settings_from_dict
from src.llm.budget_tracker import BudgetExceededError
from src.llm.client import LlmClient
from src.llm.fallback_policy import ProviderCallError, should_try_next_model


def _status_error(code: int) -> APIStatusError:
    req = httpx.Request("POST", "https://openrouter.test/v1/chat/completions")
    return APIStatusError(
        f"http {code}", response=httpx.Response(code, request=req), body=None
    )


class _FakeResponse:
    """Just enough shape for extract_usage + choices[0].message.content."""

    def __init__(self, content: str) -> None:
        self.usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                      "cost": 0.001}
        msg = type("Msg", (), {"content": content})()
        self.choices = [type("Choice", (), {"message": msg})()]


class _FakeBudget:
    def __init__(self, *, allowed_calls: int | None = None) -> None:
        self.checks = 0
        self.recorded: list[float | None] = []
        self._allowed_calls = allowed_calls  # None = unlimited

    def check_allowed(self):
        self.checks += 1
        if self._allowed_calls is not None and self.checks > self._allowed_calls:
            raise BudgetExceededError("cap reached")
        return True, 0.0

    def record_cost(self, usd):
        self.recorded.append(usd)


def _client(monkeypatch, tmp_path, *, chain, script):
    """LlmClient whose per-model call follows `script`: {model: exception|content}."""
    settings = build_settings_from_dict(
        {"openrouter_api_key": "k", "openrouter_model": "primary",
         "model_chain": chain, "data_dir": tmp_path}
    )
    budget = _FakeBudget()
    client = LlmClient(settings, budget=budget)

    def _fake_call(messages, model_name):
        outcome = script[model_name]
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResponse(outcome)

    monkeypatch.setattr(client, "_call_with_retry", _fake_call)
    return client, budget


# --- policy table (S1) ---


@pytest.mark.parametrize("code", [400, 402, 404, 408, 429, 500, 502, 503, 529])
def test_policy_provider_statuses_fall_back(code):
    assert should_try_next_model(_status_error(code)) is True


@pytest.mark.parametrize("code", [401, 403])
def test_policy_auth_statuses_never_fall_back(code):
    assert should_try_next_model(_status_error(code)) is False


def test_policy_budget_and_unknown_errors_never_fall_back():
    assert should_try_next_model(BudgetExceededError("cap")) is False
    assert should_try_next_model(RuntimeError("OPENROUTER_API_KEY is not set")) is False
    assert should_try_next_model(ProviderCallError("retries exhausted")) is True
    assert should_try_next_model(APITimeoutError(request=None)) is True


# --- chain walk (S2) ---


def test_no_chain_is_single_call_no_fallback_metadata(monkeypatch, tmp_path):
    client, budget = _client(monkeypatch, tmp_path, chain=None, script={"primary": "ok"})
    result = client.complete([{"role": "user", "content": "hi"}])
    assert (result.model, result.content, result.fallback_from) == ("primary", "ok", ())
    assert budget.checks == 1 and budget.recorded == [0.001]


def test_402_on_primary_falls_back_to_secondary(monkeypatch, tmp_path):
    client, budget = _client(
        monkeypatch, tmp_path, chain=["a", "b"],
        script={"a": _status_error(402), "b": "saved"},
    )
    result = client.complete([{"role": "user", "content": "hi"}])
    assert result.model == "b" and result.content == "saved"
    assert result.fallback_from == ("a",)
    assert budget.checks == 2  # re-checked before EVERY attempt
    assert budget.recorded == [0.001]  # the 402 attempt was not billed


def test_401_raises_without_fallback(monkeypatch, tmp_path):
    client, _ = _client(
        monkeypatch, tmp_path, chain=["a", "b"],
        script={"a": _status_error(401), "b": "never"},
    )
    with pytest.raises(APIStatusError):
        client.complete([{"role": "user", "content": "hi"}])


def test_budget_cap_stops_the_chain_before_fallback_attempt(monkeypatch, tmp_path):
    client, budget = _client(
        monkeypatch, tmp_path, chain=["a", "b"],
        script={"a": _status_error(402), "b": "never"},
    )
    budget._allowed_calls = 1  # cap hits after the first attempt's check
    with pytest.raises(BudgetExceededError):
        client.complete([{"role": "user", "content": "hi"}])


def test_empty_content_falls_back_but_last_model_may_return_empty(monkeypatch, tmp_path):
    client, budget = _client(
        monkeypatch, tmp_path, chain=["a", "b"], script={"a": "  ", "b": ""}
    )
    result = client.complete([{"role": "user", "content": "hi"}])
    assert result.model == "b" and result.content == ""  # last model: pre-v4 behavior
    assert result.fallback_from == ("a",)
    assert budget.recorded == [0.001, 0.001]  # BOTH billed attempts counted


def test_exhausted_chain_raises_with_context(monkeypatch, tmp_path):
    client, _ = _client(
        monkeypatch, tmp_path, chain=["a", "b"],
        script={"a": _status_error(502), "b": _status_error(429)},
    )
    with pytest.raises(APIStatusError):  # last model's error propagates (has_next=False)
        client.complete([{"role": "user", "content": "hi"}])


def test_explicit_model_param_bypasses_chain(monkeypatch, tmp_path):
    client, _ = _client(
        monkeypatch, tmp_path, chain=["a", "b"], script={"solo": "direct"}
    )
    result = client.complete([{"role": "user", "content": "hi"}], model="solo")
    assert result.model == "solo" and result.fallback_from == ()


# --- config (S3) ---


def test_model_chain_config_shapes(tmp_path):
    base = {"openrouter_model": "m", "data_dir": tmp_path}
    assert build_settings_from_dict(base).effective_model_chain() == ("m",)
    assert build_settings_from_dict({**base, "model_chain": []}).model_chain == ()
    s = build_settings_from_dict({**base, "model_chain": ["a", " b "]})
    assert s.effective_model_chain() == ("a", "b")
    s = build_settings_from_dict({**base, "model_chain": "a, b,,"})
    assert s.effective_model_chain() == ("a", "b")
    with pytest.raises(ValueError):
        build_settings_from_dict({**base, "model_chain": 42})
    with pytest.raises(ValueError):
        build_settings_from_dict({**base, "model_chain": [" ", ""]})
    with pytest.raises(ValueError):  # unquoted yaml scalar (float) must fail at load
        build_settings_from_dict({**base, "model_chain": ["a", 2.5]})


def test_chain_overriding_configured_model_warns(monkeypatch, tmp_path, caplog):
    client, _ = _client(
        monkeypatch, tmp_path, chain=["other-a", "other-b"], script={"other-a": "ok"}
    )
    with caplog.at_level("WARNING", logger="src.llm.client"):
        result = client.complete([{"role": "user", "content": "hi"}])
    assert result.model == "other-a"
    assert any("overrides configured model" in r.message for r in caplog.records)


def test_profile_yaml_chain_wins_over_env(monkeypatch, tmp_path):
    from src.profile.loader_mapping import build_settings_dict

    monkeypatch.setenv("OPENROUTER_MODEL_CHAIN", "env-a,env-b")
    d = build_settings_dict({"model_chain": ["yaml-a", "yaml-b"]}, tmp_path)
    assert d["model_chain"] == ["yaml-a", "yaml-b"]
    d = build_settings_dict({}, tmp_path)
    assert d["model_chain"] == "env-a,env-b"
    monkeypatch.delenv("OPENROUTER_MODEL_CHAIN")
    assert "model_chain" not in build_settings_dict({}, tmp_path)
