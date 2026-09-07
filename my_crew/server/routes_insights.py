"""Read-only fleet insights for the system hub's Số liệu tab.

Three aggregates the backend already computed for chat or for the CLI, now as JSON so
the web can draw them: the sprint/team routing retro (`ops_route_stats`), per-tool
call health from the audit trails (`audit.tool_stats`), and spend per engine from the
captures table. Same posture as `routes_observability`: GET only, no Gateway, a fresh
install answers with empty shapes, and one unreadable agent degrades to `skipped`
rather than a 500.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter

from my_crew.agent.ops_route_stats import aggregate_route_stats
from my_crew.audit.tool_stats import collect_tool_stats_from_paths
from my_crew.runtime.agent_paths import agent_data_dir
from my_crew.runtime.capture_store import CaptureStore
from my_crew.runtime.registry import load_registry
from my_crew.runtime.team_task_paths import capture_db_path, team_tasks_db_path, team_tasks_root
from my_crew.runtime.team_task_store import TeamTaskStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/insights", tags=["insights"])

_DAYS_MAX = 90


def _since_iso(days: int) -> str | None:
    """ISO prefix for "the last N days"; 0 (or less) means the whole history."""
    if days <= 0:
        return None
    days = min(days, _DAYS_MAX)
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")


@router.get("/route-stats")
def route_stats() -> dict:
    """The routing retro as data. Empty (total 0) before the first routed task."""
    path = team_tasks_db_path()
    if not path.exists():
        return aggregate_route_stats([])
    store = TeamTaskStore(path)
    try:
        routes = store.list_routes()
    finally:
        store.close()
    return aggregate_route_stats(routes)


@router.get("/tool-stats")
def tool_stats(days: int = 7) -> dict:
    """Per-tool call health pooled over every agent's audit trail plus the team trail.

    `days` bounds the window (default a week, max 90; 0 = everything). Agents whose
    data dir cannot be resolved are listed in `skipped`, not raised.
    """
    paths: list[Path] = []
    agents: list[str] = []
    skipped: list[str] = []
    for entry in load_registry():
        try:
            paths.append(agent_data_dir(entry.id) / "audit" / "audit.jsonl")
            agents.append(entry.id)
        except Exception:  # noqa: BLE001 — one broken agent must not blank the fleet view
            logger.warning("tool-stats: skipping agent %s", entry.id)
            skipped.append(entry.id)
    paths.append(team_tasks_root() / "audit" / "audit.jsonl")
    stats = collect_tool_stats_from_paths(paths, since=_since_iso(days))
    return {
        "days": max(0, min(days, _DAYS_MAX)),
        "tools": [s.as_dict() for s in stats],
        "agents": agents,
        "skipped": skipped,
    }


@router.get("/engine-costs")
def engine_costs(days: int = 7) -> dict:
    """Spend, volume and failure count per engine over the captures window."""
    path = capture_db_path()
    clamped = max(0, min(days, _DAYS_MAX))
    if not path.exists():
        return {"days": clamped, "engines": [], "total_cost_usd": 0.0, "total_calls": 0}
    store = CaptureStore(path)
    try:
        engines = store.aggregate_by_engine(since=_since_iso(days))
    finally:
        store.close()
    return {
        "days": clamped,
        "engines": engines,
        "total_cost_usd": round(sum(e["cost_usd"] for e in engines), 6),
        "total_calls": sum(e["calls"] for e in engines),
    }
