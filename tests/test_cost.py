"""Cost extraction from OpenRouter-style responses (cost present / absent / garbled)."""

from __future__ import annotations

from src.llm.cost import extract_usage


def test_cost_on_usage():
    resp = {
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": 0.0021}
    }
    u = extract_usage(resp)
    assert u.prompt_tokens == 10
    assert u.completion_tokens == 5
    assert u.total_tokens == 15
    assert u.cost_usd == 0.0021


def test_cost_absent_returns_none_and_derives_total():
    resp = {"usage": {"prompt_tokens": 3, "completion_tokens": 4}}
    u = extract_usage(resp)
    assert u.cost_usd is None
    assert u.total_tokens == 7  # derived when total missing


def test_cost_at_top_level():
    resp = {"usage": {"prompt_tokens": 1, "completion_tokens": 1}, "cost": 0.01}
    assert extract_usage(resp).cost_usd == 0.01


def test_garbled_cost_returns_none():
    resp = {"usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": "not-a-number"}}
    assert extract_usage(resp).cost_usd is None


def test_missing_usage_is_zero():
    u = extract_usage({})
    assert u.prompt_tokens == 0
    assert u.total_tokens == 0
    assert u.cost_usd is None
