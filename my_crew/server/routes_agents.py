"""Read-only agent routes (v2 M2-P6): GET /api/agents, GET /api/agents/{id}/status.

Thin router over `agent_views`. Unknown-id → 404. No graph run here (that is the
/trigger route in Slice 2).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from my_crew.server import agent_views

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
def get_agents() -> list[dict]:
    """List every registry agent with name / enabled / last run."""
    return agent_views.list_agents()


@router.get("/{agent_id}/status")
def get_agent_status(agent_id: str) -> dict:
    """Per-agent status: enabled, last run, budget vs cap, pending-approval count."""
    try:
        return agent_views.agent_status(agent_id)
    except agent_views.UnknownAgentError:
        raise HTTPException(status_code=404, detail=f"unknown agent {agent_id!r}") from None
