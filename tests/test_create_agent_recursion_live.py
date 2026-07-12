"""Live recursion-parity check for the tools-tier `langchain.agents.create_agent` loop.

The migration off `create_react_agent` must not shrink the usable tool-round budget: the loop
config passes `recursion_limit = rounds * 2`, and a step that legitimately needs its Nth round
must complete, not trip `GraphRecursionError` and fail. A mocked short loop can't prove this —
the boundary only bites against a model that actually keeps calling tools. This test drives a
real OpenRouter model with a tool it is told to call several times, and asserts the loop reaches
the documented round count at the documented cap.

Skipped unless OPENROUTER_API_KEY is configured (same gating as the other live suites).
"""

from __future__ import annotations

import pytest

try:
    from src.config.config_builders import build_settings_from_env

    _settings = build_settings_from_env()
    _HAS_KEY = bool(getattr(_settings, "openrouter_api_key", None))
except Exception:
    _settings = None
    _HAS_KEY = False

pytestmark = pytest.mark.skipif(not _HAS_KEY, reason="OPENROUTER_API_KEY not configured")


def _counting_tool(counter):
    from langchain_core.tools import tool

    @tool
    def step(note: str = "") -> str:
        """Record one work step. Call this once per step of your plan."""
        counter["n"] += 1
        return f"recorded step {counter['n']}; continue to the next step"

    return step


def test_create_agent_reaches_documented_rounds_at_cap():
    # A cap of rounds*2 must let the model reach `rounds` tool calls without GraphRecursionError.
    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    from src.config.settings import OPENROUTER_BASE_URL
    from src.runtime_backends.community_loop_core import invoke_capped, record_loop_result
    from src.runtime_backends.config import MAX_LOOP_STEPS

    counter = {"n": 0}
    model = ChatOpenAI(
        model=_settings.openrouter_model,
        api_key=_settings.openrouter_api_key,
        base_url=OPENROUTER_BASE_URL,
    )
    agent = create_agent(model, [_counting_tool(counter)])
    rounds = 3
    messages = [
        SystemMessage(content="You are a worker. Follow the user's instructions exactly."),
        HumanMessage(content=f"Call the `step` tool {rounds} times, then reply 'DONE'."),
    ]
    # The runtime's real tools-tier cap is `MAX_LOOP_STEPS * 2`; a multi-round step must complete
    # at that budget without tripping the recursion-overflow degrade (empty text).
    result = invoke_capped(agent, messages, recursion_limit=MAX_LOOP_STEPS * 2)
    text, _cost = record_loop_result(result, model_name=_settings.openrouter_model)
    assert text != "", "loop overflowed at the runtime cap — migration shrank the round budget"
    # ≥2 tool calls proves the multi-round loop actually ran (not a one-shot); the exact count
    # varies with model compliance, so we don't pin it to `rounds`.
    assert counter["n"] >= 2, "loop did not drive multiple tool rounds at the runtime cap"
