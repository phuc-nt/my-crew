"""Agent graph state (Phase 0 — minimal).

This is the typed state threaded through the LangGraph nodes. Phase 0 only needs
to carry a user message in and the LLM reply + cost out. The full reporting state
(raw_signals, analysis, risks, planned_actions, report_draft, ...) arrives in
Phase 1 per system-architecture.md §3.
"""

from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict


class AgentState(TypedDict):
    """Minimal hello-agent state. Optional keys are filled by nodes."""

    user_input: str
    llm_response: str
    cost_usd: float | None


class ReportState(TypedDict, total=False):
    """State for the reporting flow: perceive→analyze→compose→deliver.

    `total=False` so each node fills its slice. State holds ONLY serializable
    primitives (the checkpointer persists this): `risks` as a list of plain dicts,
    `report_text` the composed detail body, plus the delivery outcome. The heavy
    fetched models (Issue/PR/CiRun) stay in the graph closure, not in state.
    """

    risks: list[dict[str, Any]]  # serialized Risk dicts
    report_text: str  # Slice 2: the Confluence detail body (storage HTML)
    cost_usd: float | None
    delivered: bool
    delivery_summary: str  # e.g. "confluence=executed slack=executed url=..."
    # M2-P5: the Lớp B resume decision ("approve" | "reject") written by the
    # `approval_gate` node after a graph-native interrupt resumes. Unset on the
    # internal (pass-through) path. Primitive ⇒ checkpoint-safe.
    approval_decision: str
    # v8 M23: True when the trust ladder auto-approved a scheduled external report at the
    # gate (no human interrupt). The worker copies it onto the run event for the CEO's
    # "đã tự duyệt" view. Unset (⇒ falsy) on every non-auto path.
    auto_approved: bool
    # M2-P6 Slice 4: the Slack short body built at compose (URL-free), checkpointed so
    # deliver can post the CORRECT short on resume without the closure box (which is
    # empty after a graph rebuild). The detail link is injected in deliver. Primitive.
    slack_short: str
    # M2-P8 Slice 3: count of memory facts the `remember` node persisted (0 when gated
    # out — dry-run / not-delivered / external). Observability only.
    memory_written: int
    # xlsx report artifact path (resource/OKR), built at compose from the live snapshot
    # and emailed as a Lớp B attachment at deliver. Only the string path is checkpointed
    # (resume-safe); unset when no email channel is configured.
    xlsx_path: str
