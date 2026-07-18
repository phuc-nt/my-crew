"""v35 P1: tool-body failures must feed back to the LLM as text, never kill the graph.

With the pinned langchain, create_agent's ToolNode only returns SCHEMA errors
(ToolInvocationError) to the model; any exception raised by the tool body propagates and
fails the whole graph invoke. `tool_error_guard` converts those into "⚠️" strings — a
policy block reads "bị từ chối" (don't retry), a transient failure reads "lỗi" (try
another way). Loop-control exceptions (GraphInterrupt) must pass through untouched.
"""

from __future__ import annotations

import pytest

from my_crew.runtime_backends.read_only_toolset import (
    ToolPolicyError,
    build_read_toolset,
    tool_error_guard,
)


def _raising(exc):
    def _fn(args):
        raise exc
    return _fn


def test_guard_turns_body_exception_into_error_string():
    guarded = tool_error_guard("jira.issues", _raising(ConnectionError("boom 500")))
    out = guarded({})
    assert out.startswith("⚠️ tool jira.issues lỗi:")
    assert "boom 500" in out


def test_guard_turns_policy_error_into_refusal_string():
    exc = ToolPolicyError("refused by policy: security")
    guarded = tool_error_guard("jira.issues", _raising(exc))
    out = guarded({})
    assert out.startswith("⚠️ tool jira.issues bị từ chối:")
    assert "security" in out
    # The two shapes are distinct — the model must be able to tell block from breakage.
    assert "lỗi:" not in out


def test_guard_happy_path_is_passthrough():
    guarded = tool_error_guard("x", lambda args: {"ok": args["q"]})
    assert guarded({"q": 1}) == {"ok": 1}


def test_guard_never_swallows_graph_interrupt():
    from langgraph.errors import GraphInterrupt

    guarded = tool_error_guard("x", _raising(GraphInterrupt()))
    with pytest.raises(GraphInterrupt):
        guarded({})


def test_guard_never_swallows_system_base_exceptions():
    guarded = tool_error_guard("x", _raising(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        guarded({})


def test_guard_bounds_and_scrubs_error_message():
    # Fake secret assembled at runtime so no literal key-shaped string sits in this file.
    fake_key = "sk-" + "abcdefghijklmnop123456"
    long_msg = "x" * 1000 + " " + fake_key + " \x00\x07"
    guarded = tool_error_guard("web.scrape", _raising(RuntimeError(long_msg)))
    out = guarded({})
    assert len(out) < 400  # prefix + capped message
    assert fake_key not in out
    assert "\x00" not in out and "\x07" not in out


def test_built_toolset_degrades_instead_of_raising(monkeypatch):
    """The real toolset path: a read tool whose body raises returns ⚠️ text."""
    import my_crew.tools.github_read as gh

    monkeypatch.setattr(gh, "get_open_prs", lambda config=None: (_ for _ in ()).throw(
        TimeoutError("api timeout")))

    class Cfg:
        pass

    tools = build_read_toolset(Cfg(), audience="internal")
    out = tools["github.prs"]({})
    assert isinstance(out, str) and out.startswith("⚠️ tool github.prs lỗi:")


def test_built_toolset_policy_block_reads_as_refusal(monkeypatch):
    """classify hard-block (Lớp A) → refusal string, not a crash; classify still ran."""
    import my_crew.actions.hard_block as hb

    calls = []

    class _Verdict:
        blocked = True
        reason = "test-block"

        class category:  # noqa: N801 — mimic the enum-carrying attr shape
            value = "security"

    def _spy(action, **kw):
        calls.append(action.get("tool"))
        return _Verdict()

    monkeypatch.setattr(hb, "classify", _spy)

    class Cfg:
        pass

    tools = build_read_toolset(Cfg(), audience="internal")
    out = tools["jira.issues"]({})
    assert out.startswith("⚠️ tool jira.issues bị từ chối:")
    assert "jira.issues" in calls  # audit chokepoint still exercised


def test_create_agent_loop_survives_raising_tool():
    """Integration through REAL create_agent: tool raises mid-loop → model sees ⚠️ text
    and the loop continues to a final answer instead of the invoke exploding."""
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage, HumanMessage

    from my_crew.runtime_backends.react_loop import _as_lc_tools

    class _ToolCallingFake(GenericFakeChatModel):
        # GenericFakeChatModel raises NotImplementedError on bind_tools; the scripted
        # messages already carry tool_calls, so binding is a no-op here.
        def bind_tools(self, tools, **kwargs):
            return self

    # Turn 1: model calls the (broken) tool. Turn 2: model answers using the ⚠️ feedback.
    tool_call_msg = AIMessage(
        content="",
        tool_calls=[{"name": "jira_issues", "args": {"query": "open"}, "id": "c1"}],
    )
    final_msg = AIMessage(content="done without jira")
    model = _ToolCallingFake(messages=iter([tool_call_msg, final_msg]))

    from langchain.agents import create_agent

    broken = {"jira.issues": _raising(ConnectionError("jira down"))}
    agent = create_agent(model, _as_lc_tools(broken))
    result = agent.invoke({"messages": [HumanMessage(content="check jira")]})

    contents = [str(getattr(m, "content", "")) for m in result["messages"]]
    assert any("⚠️ tool jira.issues lỗi" in c for c in contents)  # feedback reached the loop
    assert contents[-1] == "done without jira"  # loop finished normally
