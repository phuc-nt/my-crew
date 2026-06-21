"""Agent graph state (Phase 0 — minimal).

This is the typed state threaded through the LangGraph nodes. Phase 0 only needs
to carry a user message in and the LLM reply + cost out. The full reporting state
(raw_signals, analysis, risks, planned_actions, report_draft, ...) arrives in
Phase 1 per system-architecture.md §3.
"""

from __future__ import annotations

from typing_extensions import TypedDict


class AgentState(TypedDict):
    """Minimal hello-agent state. Optional keys are filled by nodes."""

    user_input: str
    llm_response: str
    cost_usd: float | None
