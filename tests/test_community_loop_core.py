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


def test_tools_tier_runs_without_the_optional_deep_extra(monkeypatch):
    """`loop_engine: langchain` must work on a default install.

    The scratch middleware needs the optional `deep` extra; nothing in config links the two, so
    hard-failing on the import took the whole tier down for anyone who installed without it. The
    tier degrades to no file scratch — and must then NOT promise a scratch tool in its prompt.
    """
    import builtins

    import my_crew.runtime_backends.react_loop as react_loop

    real_import = builtins.__import__

    def _no_deepagents(name, *args, **kwargs):
        if name.startswith("deepagents"):
            raise ModuleNotFoundError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_deepagents)

    seen = {}

    class _FakeAgent:
        def invoke(self, state, config=None):
            seen["messages"] = state["messages"]
            return {"messages": [_Msg("ok")]}

    def _fake_create_agent(model, tools, **kwargs):
        seen["middleware"] = kwargs.get("middleware")
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

    text, _cost = react_loop.run_react_work(
        title="t", handoff="h", context=_Ctx(), settings=_S(), tools_map={}, max_steps=4,
    )
    assert text == "ok"  # the tier still ran
    assert seen["middleware"] == []  # degraded, not a [None] that create_agent would choke on
    system = next(m for m in seen["messages"] if type(m).__name__ == "SystemMessage")
    assert react_loop._STATE_SCRATCH_CONTRACT not in system.content


@pytest.mark.skipif(not _HAS_DEEPAGENTS, reason="deepagents optional dep not installed")
def test_tools_tier_binds_file_scratch_when_the_deep_extra_is_present():
    """The degrade path must not become the ONLY path: with the extra installed the middleware is
    still built, still shell-free."""
    import my_crew.runtime_backends.react_loop as react_loop

    mw = react_loop._state_scratch_middleware()
    assert mw is not None
    assert "execute" not in [getattr(t, "name", "") for t in mw.tools]


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


# --- v74.1: cap overflow salvages the partial transcript --------------------------------------


def _overflow_agent(states, synthesized):
    """A fake compiled graph: stream yields `states` then overflows; invoke returns the
    synthesis result (recording what transcript it was given)."""
    from langgraph.errors import GraphRecursionError

    class _Agent:
        def __init__(self):
            self.invoke_input = None
            self.invoke_config = None

        def stream(self, _state, config=None, stream_mode=None):
            yield from states
            raise GraphRecursionError("cap")

        def invoke(self, state, config=None):
            self.invoke_input = state["messages"]
            self.invoke_config = config
            return {"messages": [*state["messages"], _Msg(synthesized)]}

    return _Agent()


def test_overflow_synthesizes_from_partial_and_trims_dangling_tool_call():
    from langchain_core.messages import HumanMessage

    from my_crew.runtime_backends.community_loop_core import invoke_capped

    class _ToolCallMsg(_Msg):
        def __init__(self):
            super().__init__("")
            self.tool_calls = [{"name": "web_search"}]

    fetched = _Msg("gia ChatGPT Plus: 20 USD")
    dangling = _ToolCallMsg()
    agent = _overflow_agent(
        states=[{"messages": [fetched]}, {"messages": [fetched, dangling]}],
        synthesized="tong hop tu du lieu da co",
    )
    result = invoke_capped(agent, [_Msg("de bai")], recursion_limit=4)
    assert result["messages"][-1].content == "tong hop tu du lieu da co"
    # the dangling tool-call turn was trimmed; the fetched data + instruction remain
    assert dangling not in agent.invoke_input
    assert fetched in agent.invoke_input
    assert isinstance(agent.invoke_input[-1], HumanMessage)
    assert "THIẾU" in agent.invoke_input[-1].content
    assert agent.invoke_config["recursion_limit"] == 6  # bounded synthesis turn


def test_overflow_with_no_partial_degrades_to_empty():
    from my_crew.runtime_backends.community_loop_core import invoke_capped

    agent = _overflow_agent(states=[], synthesized="never used")
    result = invoke_capped(agent, [_Msg("de bai")], recursion_limit=4)
    assert result["messages"][-1].content == ""
    assert agent.invoke_input is None  # no synthesis attempted on an empty transcript


def test_overflow_synthesis_failure_degrades_to_empty():
    from langgraph.errors import GraphRecursionError

    from my_crew.runtime_backends.community_loop_core import invoke_capped

    agent = _overflow_agent(states=[{"messages": [_Msg("mot it du lieu")]}],
                            synthesized="unused")

    def _boom(state, config=None):
        raise GraphRecursionError("cap again")

    agent.invoke = _boom
    result = invoke_capped(agent, [_Msg("de bai")], recursion_limit=4)
    assert result["messages"][-1].content == ""


def test_agent_without_stream_keeps_invoke_path():
    from my_crew.runtime_backends.community_loop_core import invoke_capped

    class _InvokeOnly:
        stream = None

        def invoke(self, state, config=None):
            return {"messages": [*state["messages"], _Msg("qua invoke")]}

    result = invoke_capped(_InvokeOnly(), [_Msg("x")], recursion_limit=4)
    assert result["messages"][-1].content == "qua invoke"
