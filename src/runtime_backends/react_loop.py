"""The create_react_agent work loop (v20 Phase 2).

Runs `langgraph.prebuilt.create_react_agent` (already in the dep tree — no `langchain`
meta-package) over the policy-shimmed read toolset, with a hard per-loop step cap. Returns
`(result_text, cost_usd)` matching the `TeamTaskDeps.run_work` contract, so the surrounding
team-step graph (self_check / rework / deliver→gateway) is untouched.

Tools are LangChain `@tool` callables wrapping the read allowlist; the model may call them in
a loop but can never reach a write — the toolset contains only reads. `recursion_limit` caps
the loop (red-team H2 runaway).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

#: Per-tool description so the model passes the RIGHT argument (e.g. a URL for web.scrape, not
#: the question text). Falls back to a generic read description for unlisted tools.
_TOOL_DESCRIPTIONS = {
    "web.scrape": "Đọc TOÀN BỘ nội dung của MỘT URL web công khai (http/https) và trả về "
                  "markdown. Tham số `query` PHẢI là URL đầy đủ (vd https://example.com), "
                  "KHÔNG phải câu hỏi. Read-only, không ghi.",
}


def _as_lc_tools(tools_map: dict[str, Callable[[dict], Any]]) -> list:
    """Wrap read callables as LangChain tools the react agent can invoke.

    Each tool takes a single free-form `query` string (the model's ask); the underlying read
    callable receives it as `{"query": ...}`. A permissive one-string schema avoids brittle
    per-tool arg models. Per-tool descriptions (`_TOOL_DESCRIPTIONS`) tell the model what to put
    in `query` — critical for web.scrape, which needs a URL rather than a question.
    """
    from langchain_core.tools import tool as lc_tool

    lc_tools = []
    for name, fn in tools_map.items():
        desc = _TOOL_DESCRIPTIONS.get(name, "Read-only tool. Returns internal data; cannot write.")

        def _make(f, tool_name, description):
            @lc_tool(tool_name.replace(".", "_"), description=description)
            def _call(query: str = "") -> str:
                return str(f({"query": query}))
            return _call

        lc_tools.append(_make(fn, name, desc))
    return lc_tools


def run_react_work(
    *, title: str, handoff: str, context, settings, tools_map, max_steps: int,
    telemetry=None,
) -> tuple[str, float | None]:
    """Run one team-step's work as a capped tool-calling loop. Returns (text, cost_usd).

    `telemetry` (optional StepTelemetry) receives the summed token counts + cost provenance
    for this attempt; cost itself still returns on the tuple. Absent collector = no-op, so
    the contract and behavior are byte-identical for callers that do not wire it.
    """
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    from src.config.settings import OPENROUTER_BASE_URL
    from src.llm.model_pricing import estimate_cost
    from src.llm.team_task_prompt import build_team_step_messages
    from src.runtime.step_telemetry import sum_usage_metadata

    # Reuse the native system+user prompt so persona/skills/company-docs/red-lines are identical;
    # we only change HOW the model produces text (loop vs one-shot), not WHAT it is told.
    msgs = build_team_step_messages(
        step_title=title, handoff_context=handoff,
        persona=getattr(context, "persona", ""), project=getattr(context, "project", ""),
        memory=getattr(context, "memory", ""), capability=getattr(context, "capability", ""),
    )
    system = next((m["content"] for m in msgs if m["role"] == "system"), "")
    user = next((m["content"] for m in msgs if m["role"] == "user"), title)

    # LangChain chat model pointed at OpenRouter (same base URL/model as LlmClient). Only used
    # by the react loop; the native path keeps the raw OpenAI SDK client unchanged.
    model = ChatOpenAI(
        model=settings.openrouter_model,
        api_key=settings.openrouter_api_key,
        base_url=OPENROUTER_BASE_URL,
    )
    agent = create_react_agent(model, _as_lc_tools(tools_map))
    result = agent.invoke(
        {"messages": [SystemMessage(content=system), HumanMessage(content=user)]},
        config={"recursion_limit": max_steps * 2},  # super-steps ≈ 2× tool rounds
    )
    messages = result["messages"]
    final = messages[-1]
    text = getattr(final, "content", "") or ""
    # Estimate cost from summed token usage × the per-model price table (LangChain's OpenRouter
    # path does not surface a provider cost here). Missing usage/price → None (never fabricated);
    # the monthly budget_tracker remains the hard backstop.
    in_tok, out_tok = sum_usage_metadata(messages)
    cost = estimate_cost(settings.openrouter_model, in_tok, out_tok)
    if telemetry is not None:
        telemetry.record(input_tokens=in_tok, output_tokens=out_tok, cost_source="estimated")
    return str(text), cost
