"""Read-only JSON API for the M4 React visualization dashboard (v2 M4-S1).

Thin routes only — each delegates to `visualize_views` (which projects to a non-PII
allowlist) and maps an unknown agent id to 404. Mirrors the clean route→view split at
`routes_agents.py`. All routes live under `/api/` so a later auth middleware can gate
`/api/*` without touching handlers. Adds NO write path: the Action Gateway is untouched.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.server import visualize_views
from src.server.agent_views import UnknownAgentError

router = APIRouter(prefix="/api", tags=["visualize"])


def _guard(fn, *args, **kwargs):
    """Run a view, mapping the shared UnknownAgentError sentinel to a 404."""
    try:
        return fn(*args, **kwargs)
    except UnknownAgentError as exc:
        raise HTTPException(status_code=404, detail=f"unknown agent {str(exc)!r}") from exc


@router.get("/runs/{agent_id}")
def get_runs(agent_id: str, limit: int = 100) -> dict:
    """Run timeline (newest-first, allowlisted run-events)."""
    return _guard(visualize_views.runs_view, agent_id, limit=limit)


@router.get("/cost/{agent_id}")
def get_cost(agent_id: str) -> dict:
    """Monthly cost series (last 12 months) + cap/warn-ratio."""
    return _guard(visualize_views.cost_view, agent_id)


@router.get("/memory/{agent_id}")
def get_memory(agent_id: str, audience: str = "internal") -> dict:
    """Remembered facts — INTERNAL-ONLY (`audience=external` ⇒ no facts)."""
    return _guard(visualize_views.memory_view, agent_id, audience=audience)


@router.get("/automation/{agent_id}")
def get_automation(agent_id: str) -> dict:
    """Pending Lớp B proposals (action summarized, not raw)."""
    return _guard(visualize_views.automation_view, agent_id)


@router.get("/audit/{agent_id}")
def get_audit(agent_id: str, limit: int = 50) -> dict:
    """Guardrail events: aggregated verdict counts + recent allowlisted rows."""
    return _guard(visualize_views.audit_view, agent_id, limit=limit)


@router.get("/company/activity")
def get_company_activity(
    limit: int = 100,
    since: str | None = None,
    agent: str | None = None,
    verdict: str | None = None,
) -> dict:
    """Fleet-wide activity timeline (audit + runs + captures, allowlisted, bounded)."""
    from src.server.fleet_activity import fleet_activity

    return _guard(fleet_activity, limit=limit, since=since, agent=agent, verdict=verdict)
