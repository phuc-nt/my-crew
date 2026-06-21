"""Minimal LangGraph agent (Phase 0): perceive -> respond.

Proves the graph lifecycle (CLI -> graph -> 1 LLM call -> output) with a SQLite
checkpointer wired in. The full perceive -> analyze -> decide -> compose_report
-> deliver flow (system-architecture.md §3) is Phase 1; Phase 0 keeps it to an
LLM echo so the wiring is verifiable end to end.

`build_graph` accepts an optional LlmClient so the graph can be built and
compiled without a key (the client is only constructed/called inside the node).
"""

from __future__ import annotations

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agent.state import AgentState
from src.llm.client import LlmClient


def _perceive(state: AgentState) -> dict:
    """Normalize input. Phase 0: passthrough. Phase 1 wires tool READs here."""
    return {"user_input": state["user_input"]}


def _make_respond(client: LlmClient | None):
    """Build the respond node, lazily creating the LLM client on first call."""
    holder: dict[str, LlmClient] = {}
    if client is not None:
        holder["client"] = client

    def _respond(state: AgentState) -> dict:
        # Lazy build so graph construction needs no API key.
        if "client" not in holder:
            holder["client"] = LlmClient()
        result = holder["client"].complete(
            [{"role": "user", "content": state["user_input"]}]
        )
        return {"llm_response": result.content, "cost_usd": result.cost_usd}

    return _respond


def build_graph(
    checkpointer: SqliteSaver | None = None,
    *,
    client: LlmClient | None = None,
) -> CompiledStateGraph:
    """Build and compile the minimal agent graph.

    `checkpointer` is optional so the graph can be compiled in tests without a DB.
    """
    builder = StateGraph(AgentState)
    builder.add_node("perceive", _perceive)
    builder.add_node("respond", _make_respond(client))
    builder.add_edge(START, "perceive")
    builder.add_edge("perceive", "respond")
    builder.add_edge("respond", END)
    return builder.compile(checkpointer=checkpointer)
