"""`LlmClient.complete_with_tools` — the thin tool loop's model-call seam.

Same budget gate / retry / chain-fallback semantics as `complete`, but returns the raw
assistant message (tool_calls + reasoning passthrough) and the finish_reason, because a
tool loop needs the wire shape, not just the text.
"""

from __future__ import annotations

import my_crew.llm.client as c


def _client():
    from my_crew.config.config_builders import build_settings_from_dict

    s = build_settings_from_dict({"openrouter_api_key": "k", "openrouter_model": "x/y"})
    return c.LlmClient(s)


class _Msg:
    """Duck-typed SDK message: model_dump() like pydantic."""

    def __init__(self, dump: dict):
        self._dump = dump

    def model_dump(self) -> dict:
        return dict(self._dump)


def _resp(message: dict, finish_reason: str = "stop", cost: float = 0.001) -> dict:
    class _Choice:
        pass

    class _R:
        pass

    choice = _Choice()
    choice.message = _Msg(message)
    choice.finish_reason = finish_reason
    r = _R()
    r.choices = [choice]
    r.usage = {"prompt_tokens": 10, "completion_tokens": 5, "cost": cost}
    return r


def _install(monkeypatch, cl, responses: list):
    """Feed canned responses to _call_with_retry, capturing kwargs."""
    seen = []

    def _fake(messages, model_name, **kw):
        seen.append({"messages": messages, "model": model_name, **kw})
        return responses.pop(0)

    monkeypatch.setattr(cl, "_call_with_retry", _fake)
    return seen


_TOOLS = [{"type": "function", "function": {"name": "web_search", "parameters": {}}}]


def test_returns_message_finish_reason_and_accounting(monkeypatch):
    cl = _client()
    msg = {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "t1", "type": "function",
                        "function": {"name": "web_search", "arguments": "{}"}}],
        "reasoning": "need facts",
    }
    seen = _install(monkeypatch, cl, [_resp(msg, "tool_calls")])

    ex = cl.complete_with_tools(
        [{"role": "user", "content": "hi"}], _TOOLS, role="worker"
    )
    assert ex.finish_reason == "tool_calls"
    assert ex.message["tool_calls"][0]["function"]["name"] == "web_search"
    assert ex.message["reasoning"] == "need facts"
    assert ex.result.cost_usd == 0.001
    assert ex.result.prompt_tokens == 10
    # tools reached the wire
    assert seen[0]["tools"] is _TOOLS


def test_empty_content_with_tool_calls_is_not_a_fallback(monkeypatch):
    """A tool-call turn legitimately has no text — must NOT trigger the empty-content
    fallback that `complete` uses."""
    from my_crew.config.config_builders import build_settings_from_dict

    s = build_settings_from_dict({
        "openrouter_api_key": "k", "openrouter_model": "x/y",
        "model_chain": ["x/y", "x/z"],
    })
    cl = c.LlmClient(s)
    msg = {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": "t1", "type": "function",
                        "function": {"name": "web_search", "arguments": "{}"}}],
    }
    _install(monkeypatch, cl, [_resp(msg, "tool_calls")])
    ex = cl.complete_with_tools([{"role": "user", "content": "hi"}], _TOOLS)
    assert ex.result.model == "x/y"
    assert ex.result.fallback_from == ()


def test_empty_content_no_tool_calls_falls_back_to_next_model(monkeypatch):
    from my_crew.config.config_builders import build_settings_from_dict

    s = build_settings_from_dict({
        "openrouter_api_key": "k", "openrouter_model": "x/y",
        "model_chain": ["x/y", "x/z"],
    })
    cl = c.LlmClient(s)
    empty = {"role": "assistant", "content": ""}
    good = {"role": "assistant", "content": "done"}
    _install(monkeypatch, cl, [_resp(empty), _resp(good)])
    ex = cl.complete_with_tools([{"role": "user", "content": "hi"}], _TOOLS)
    assert ex.result.model == "x/z"
    assert ex.result.fallback_from == ("x/y",)
    assert ex.message["content"] == "done"


def test_budget_cost_recorded(monkeypatch):
    cl = _client()
    recorded = []
    monkeypatch.setattr(cl._budget, "record_cost", lambda cost: recorded.append(cost))
    _install(monkeypatch, cl, [_resp({"role": "assistant", "content": "ok"}, cost=0.02)])
    cl.complete_with_tools([{"role": "user", "content": "hi"}], _TOOLS)
    assert recorded == [0.02]


def test_length_finish_reason_surfaced(monkeypatch):
    cl = _client()
    msg = {"role": "assistant", "content": "trunc"}
    _install(monkeypatch, cl, [_resp(msg, "length")])
    ex = cl.complete_with_tools([{"role": "user", "content": "hi"}], _TOOLS)
    assert ex.finish_reason == "length"
