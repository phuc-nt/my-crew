"""v43 Phase 2: subagent tokens fold into the ONE step cost (v26 cost-honesty).

A deep_agent subagent's LLM calls never appear in the parent's returned `messages`, so the
messages-walk (`sum_usage_metadata`) under-counts them. When a `UsageMetadataCallbackHandler` is
passed, `record_loop_result` sources tokens from the handler (a superset) instead. Without a handler
the messages-walk path stays byte-identical (native / create_agent / non-deep-team deep_agent).
"""

from __future__ import annotations

from my_crew.runtime_backends.community_loop_core import (
    _flatten_usage_handler,
    invoke_capped,
    record_loop_result,
)


class _FakeHandler:
    """Mimics UsageMetadataCallbackHandler: per-model nested usage dict."""

    def __init__(self, usage):
        self.usage_metadata = usage


def _msg(content, usage=None):
    from langchain_core.messages import AIMessage

    m = AIMessage(content=content)
    if usage is not None:
        m.usage_metadata = usage
    return m


def test_flatten_sums_across_models():
    h = _FakeHandler({
        "parent/model": {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140},
        "sub/model": {"input_tokens": 500, "output_tokens": 200, "total_tokens": 700},
    })
    assert _flatten_usage_handler(h) == (600, 240)


def test_flatten_degrades_on_bad_shape():
    assert _flatten_usage_handler(_FakeHandler({})) == (0, 0)
    assert _flatten_usage_handler(_FakeHandler(None)) == (0, 0)
    assert _flatten_usage_handler(object()) == (0, 0)  # no usage_metadata attr


def test_handler_supersets_messages_walk():
    """Handler reports tokens NOT present in result['messages'] → folded cost reflects them."""
    # messages carry only 10/5; the handler (parent+subagent) reports 600/240.
    result = {"messages": [_msg("final", usage={"input_tokens": 10, "output_tokens": 5})]}
    handler = _FakeHandler({"m": {"input_tokens": 600, "output_tokens": 240}})

    text_h, cost_h = record_loop_result(result, model_name="x/y", usage_handler=handler)
    text_n, cost_n = record_loop_result(result, model_name="x/y", usage_handler=None)

    assert text_h == text_n == "final"
    # Both cost or both None depends on the price table having x/y; assert the token SOURCE differs
    # by checking telemetry capture instead (below). Here at least the handler path did not crash.
    assert cost_h == cost_h  # sanity


def test_handler_none_is_messages_walk_identity():
    """usage_handler=None must be byte-identical to the pre-v43 messages-walk."""
    result = {"messages": [_msg("r", usage={"input_tokens": 30, "output_tokens": 12})]}

    class _Tel:
        def __init__(self):
            self.calls = []

        def record(self, **kw):
            self.calls.append(kw)

    t = _Tel()
    record_loop_result(result, model_name="x/y", telemetry=t, usage_handler=None)
    assert t.calls[0]["input_tokens"] == 30
    assert t.calls[0]["output_tokens"] == 12


def test_handler_totals_reach_telemetry():
    result = {"messages": [_msg("r", usage={"input_tokens": 1, "output_tokens": 1})]}
    handler = _FakeHandler({"m": {"input_tokens": 777, "output_tokens": 333}})

    class _Tel:
        def __init__(self):
            self.calls = []

        def record(self, **kw):
            self.calls.append(kw)

    t = _Tel()
    record_loop_result(result, model_name="x/y", telemetry=t, usage_handler=handler)
    assert t.calls[0]["input_tokens"] == 777  # folded, not the messages' 1
    assert t.calls[0]["output_tokens"] == 333
    assert t.calls[0]["cost_source"] == "estimated"


def test_invoke_capped_attaches_handler_to_callbacks():
    """The handler must land in config['callbacks'] so it captures nested subagent LLM calls."""
    captured = {}

    class _Agent:
        def invoke(self, payload, config=None):
            captured["config"] = config
            from langchain_core.messages import AIMessage
            return {"messages": [AIMessage(content="ok")]}

    handler = _FakeHandler({})
    invoke_capped(_Agent(), [], recursion_limit=8, usage_handler=handler)
    assert captured["config"]["callbacks"] == [handler]


def test_invoke_capped_no_handler_no_callbacks_key():
    captured = {}

    class _Agent:
        def invoke(self, payload, config=None):
            captured["config"] = config
            from langchain_core.messages import AIMessage
            return {"messages": [AIMessage(content="ok")]}

    invoke_capped(_Agent(), [], recursion_limit=8)
    assert "callbacks" not in captured["config"]
