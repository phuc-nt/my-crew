"""The shared post-invoke tail (`record_loop_result`) + per-tier system-prompt ownership.

`record_loop_result` only turns an already-invoked result into `(text, cost)` — it never
builds the agent or binds the system prompt. These tests lock that: token summing + pricing
behave for a multi-turn result, and each tier still hands the model exactly one SystemMessage
while the shell tier keeps its `system_prompt=` binding.
"""

from __future__ import annotations

import importlib.util

import pytest

from my_crew.runtime_backends.community_loop_core import record_loop_result


class _Msg:
    def __init__(self, content, usage=None):
        self.content = content
        self.usage_metadata = usage


def test_record_loop_result_sums_multi_turn_usage_and_prices():
    # Two AIMessages carrying usage → summed input/output tokens → priced (estimated).
    result = {"messages": [
        _Msg("step 1", {"input_tokens": 10, "output_tokens": 4}),
        _Msg("final answer", {"input_tokens": 20, "output_tokens": 9}),
    ]}
    recorded = {}

    class _Tel:
        def record(self, *, input_tokens, output_tokens, cost_source):
            recorded.update(input=input_tokens, output=output_tokens, source=cost_source)

    text, cost = record_loop_result(result, model_name="minimax/minimax-m2.7", telemetry=_Tel())
    assert text == "final answer"
    assert cost is not None and cost > 0  # priced from the seeded model table
    assert recorded == {"input": 30, "output": 13, "source": "estimated"}


def test_record_loop_result_no_usage_yields_none_cost():
    # No message carries usage_metadata → cost None (never fabricated), telemetry still records.
    result = {"messages": [_Msg("done")]}
    text, cost = record_loop_result(result, model_name="minimax/minimax-m2.7")
    assert text == "done"
    assert cost is None


def test_record_loop_result_tolerates_non_str_content():
    result = {"messages": [_Msg(None)]}
    text, cost = record_loop_result(result, model_name="x/y")
    assert text == ""


# --- Per-tier system-prompt ownership: exactly one SystemMessage reaches the model ------------

_HAS_DEEPAGENTS = importlib.util.find_spec("deepagents") is not None


def _system_count(messages):
    from langchain_core.messages import SystemMessage

    return sum(1 for m in messages if isinstance(m, SystemMessage))


def test_tools_tier_sends_exactly_one_system_message(monkeypatch):
    # react loop passes system ONLY as a SystemMessage; create_agent gets no system_prompt.
    import my_crew.runtime_backends.react_loop as react_loop

    seen = {}

    class _FakeAgent:
        def invoke(self, state, config=None):
            seen["messages"] = state["messages"]
            seen["config"] = config
            return {"messages": [_Msg("ok")]}

    def _fake_create_agent(model, tools, **kwargs):
        seen["create_agent_kwargs"] = kwargs
        return _FakeAgent()

    monkeypatch.setattr("langchain.agents.create_agent", _fake_create_agent)
    monkeypatch.setattr("langchain_openai.ChatOpenAI", lambda *a, **k: object())

    class _S:
        openrouter_model = "x/y"
        openrouter_api_key = "k"

    class _Ctx:
        persona = "P"
        project = "proj"
        memory = "mem"
        capability = "cap"

    react_loop.run_react_work(
        title="t", handoff="h", context=_Ctx(), settings=_S(),
        tools_map={}, max_steps=4,
    )
    assert _system_count(seen["messages"]) == 1
    # tools tier must NOT bind system_prompt (owns its prompt via the SystemMessage only)
    assert "system_prompt" not in seen["create_agent_kwargs"]


def test_invoke_capped_forces_tracing_off_during_invoke(monkeypatch):
    # With tracing env ON, the invoke must see it OFF (blanked env), then have it restored after.
    import os

    from my_crew.runtime_backends.community_loop_core import invoke_capped

    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "fake-should-not-egress")

    seen = {}

    class _Agent:
        def invoke(self, state, config=None):
            from langsmith.utils import tracing_is_enabled

            seen["tracing_during"] = tracing_is_enabled()
            return {"messages": [_Msg("ok")]}

    invoke_capped(_Agent(), [], recursion_limit=4)
    assert seen["tracing_during"] is False  # tracer suppressed for the invoke
    # env restored afterwards (no leak across runs)
    assert os.environ.get("LANGCHAIN_TRACING_V2") == "true"
    assert os.environ.get("LANGSMITH_API_KEY") == "fake-should-not-egress"


def test_invoke_capped_degrades_on_recursion_overflow():
    # A loop that exhausts its cap yields empty text (not the echoed prompt), never raising.
    from langchain_core.messages import HumanMessage, SystemMessage
    from langgraph.errors import GraphRecursionError

    from my_crew.runtime_backends.community_loop_core import invoke_capped, record_loop_result

    class _Overflow:
        def invoke(self, state, config=None):
            raise GraphRecursionError("cap hit")

    msgs = [SystemMessage(content="sys"), HumanMessage(content="do the thing")]
    result = invoke_capped(_Overflow(), msgs, recursion_limit=8)
    text, _cost = record_loop_result(result, model_name="x/y")
    assert text == ""  # degraded to empty, NOT "do the thing"


@pytest.mark.skipif(not _HAS_DEEPAGENTS, reason="deepagents optional dep not installed")
def test_shell_tier_binds_system_prompt_and_one_system_message(monkeypatch):
    # deep loop keeps BOTH: create_deep_agent(system_prompt=<sanitized>) AND one SystemMessage.
    import my_crew.runtime_backends.deep_agent_loop as loop

    seen = {}

    class _FakeAgent:
        def invoke(self, state, config=None):
            seen["messages"] = state["messages"]
            return {"messages": [_Msg("ok")]}

    def _fake_create_deep_agent(model, backend=None, system_prompt=None):
        seen["system_prompt"] = system_prompt
        return _FakeAgent()

    monkeypatch.setattr("deepagents.create_deep_agent", _fake_create_deep_agent)
    monkeypatch.setattr("langchain_openai.ChatOpenAI", lambda *a, **k: object())
    monkeypatch.setattr(
        "my_crew.runtime_backends.sandbox_backend.build_sandbox_backend",
        lambda cfg: type("B", (), {"teardown": lambda self: None})(),
    )
    monkeypatch.setattr(
        "my_crew.runtime_backends.sandbox_teardown.teardown_sandbox", lambda b: None
    )

    class _S:
        openrouter_model = "x/y"
        openrouter_api_key = "k"

    class _Ctx:
        persona = "P"
        project = "proj"
        memory = "SECRET-mem"
        capability = "cap"

    def _identity(text):
        return text, True

    loop.run_deep_agent_work(
        title="t", handoff="h", context=_Ctx(), settings=_S(),
        sandbox_cfg={"provider": "fake"}, loop_limit=4, sanitize=_identity,
    )
    assert _system_count(seen["messages"]) == 1
    assert seen["system_prompt"] is not None  # shell tier keeps system_prompt= binding
