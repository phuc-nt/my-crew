"""Read-only view builders for the control-plane API (phase 2, plan
`260830-1311-zalo-business-fleet`).

Design decision D2 (see `plans/reports/architecture-gap-brainstorm-...report.md`):
NO db merge — this module is a thin, read-only aggregation layer over stores that
already exist (`registry`, `agent_state_reader`, `integration_health`,
`team_task_store`, `approval_store`). Every function here degrades independently:
one broken store must never blind the whole `overview()` response (phase
acceptance: "MỖI KHỐI fail-degrade độc lập").

Contract is versioned (`"v": 1`) so a future field addition/removal is a
deliberate, documented break, not a silent drift — every top-level dict this
module returns carries the same `v` key.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Contract version for every payload this module builds.
CONTRACT_VERSION = 1

#: Step-cost fields safe to surface — same allowlist discipline as
#: `routes_outputs._COST_FIELDS` (never echo a raw capture row).
_STEP_COST_FIELDS = (
    "step_id", "agent_id", "engine", "status", "step_type",
    "cost_usd", "cost_source", "input_tokens", "output_tokens", "duration_ms",
)
#: Route fields safe to surface — mirrors `routes_outputs._ROUTE_FIELDS`.
_ROUTE_FIELDS = ("mode", "source", "reason")


def _open_team_task_store():
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    return TeamTaskStore(team_tasks_db_path())


def build_task_status(task_id: str) -> dict[str, Any] | None:
    """Unified status view for ONE team task: state, steps, cost, delivery, route.

    Returns None when the task does not exist (the router maps that to 404) — every
    other partial-failure mode (route lookup, cost lookup) degrades to an empty
    sub-block instead of failing the whole status read, since those are secondary
    detail next to the task's own existence/state.
    """
    store = _open_team_task_store()
    try:
        task = store.get(task_id)
        if task is None:
            return None
        route = _safe(lambda: store.get_route(task_id) or {}, {}, "route")
    finally:
        store.close()

    steps = [
        {
            "step_id": s.step_id,
            "title": s.title,
            "assigned_to": s.assigned_to,
            "status": s.status,
            "step_type": s.step_type,
            "deps": list(s.deps),
            "cost_usd": s.cost_usd,
        }
        for s in task.steps
    ]
    cost = _safe(lambda: _task_cost_breakdown(task_id), {"total_cost_usd": 0.0, "steps": []},
                 "cost")

    return {
        "v": CONTRACT_VERSION,
        "task_id": task.id,
        "title": task.title,
        "state": {
            "status": task.status,
            "pic_id": task.pic_id,
            "room_id": task.room_id or task.id,
            "created_at": task.created_at,
        },
        "steps": steps,
        "cost": cost,
        "delivery": {
            "status": task.delivery_status,
            "attempts": task.delivery_attempts,
            "final_summary": task.final_summary,
        },
        "route": {k: str(route.get(k) or "") for k in _ROUTE_FIELDS},
    }


def _task_cost_breakdown(task_id: str) -> dict[str, Any]:
    """Per-step cost/token breakdown — same shape as `routes_outputs.team_task_cost`
    (deliberately duplicated, not imported: that route returns its OWN top-level dict
    shape, this one nests under `cost` inside the unified status payload)."""
    from my_crew.runtime.capture_store import CaptureStore
    from my_crew.runtime.team_task_paths import capture_db_path

    path = capture_db_path()
    if not path.exists():
        return {"total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0,
                "steps": []}
    store = CaptureStore(path)
    try:
        rows = store.list_for_task(task_id)
    finally:
        store.close()
    steps = [{k: r.get(k) for k in _STEP_COST_FIELDS} for r in rows]
    return {
        "total_cost_usd": round(sum(r.get("cost_usd") or 0.0 for r in rows), 6),
        "total_input_tokens": sum(r.get("input_tokens") or 0 for r in rows),
        "total_output_tokens": sum(r.get("output_tokens") or 0 for r in rows),
        "steps": steps,
    }


def _safe(fn, default: Any, block_name: str) -> Any:
    """Run `fn()`; any exception logs + degrades to `default`. Shared by every
    overview block so ONE store failure can never sink the other three (acceptance:
    fail-degrade independent per block)."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 — a broken block must degrade, not propagate
        logger.warning("control-plane overview: %s block failed", block_name, exc_info=True)
        return default


def _registry_block() -> dict[str, Any]:
    from my_crew.runtime.agent_state_reader import read_agent_state
    from my_crew.runtime.registry import load_registry

    agents = []
    for entry in load_registry():
        state = read_agent_state(entry.id)
        agents.append({
            "agent_id": entry.id,
            "enabled": entry.enabled,
            "name": state.get("name", ""),
            "domain": state.get("domain", ""),
            "last_run": state.get("last_run"),
        })
    return {"agents": agents}


def _health_block() -> dict[str, Any]:
    from my_crew.server.integration_health import integration_checks

    payload = integration_checks()
    checks = payload.get("checks", [])
    return {
        "coordinator_ok": _coordinator_ok(),
        "integrations": [
            {"id": c["id"], "label": c["label"], "ok": c["ok"]} for c in checks
        ],
    }


def _coordinator_ok() -> bool:
    """True when the coordinator heartbeat looks alive — delegates to the SAME
    check `GET /api/office/health/coordinator` uses (in-process call, not HTTP), so
    the overview never re-implements the heartbeat-staleness logic."""
    from my_crew.server.routes_office_room_chat import get_coordinator_health

    return bool(get_coordinator_health().get("alive"))


def _queue_block() -> dict[str, Any]:
    store = _open_team_task_store()
    try:
        dispatchable = store.list_dispatchable()
        stalled = store.list_stalled()
    finally:
        store.close()
    return {
        "depth": len(dispatchable),
        "running": sum(1 for t in dispatchable if t.status == "running"),
        "stalled": len(stalled),
    }


def _approvals_block() -> dict[str, Any]:
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.agent_state_reader import _read_pending
    from my_crew.runtime.registry import load_registry

    total = 0
    per_agent: dict[str, int] = {}
    for entry in load_registry():
        pending = _read_pending(agent_data_dir(entry.id))
        if pending:
            per_agent[entry.id] = len(pending)
            total += len(pending)
    return {"pending_total": total, "pending_by_agent": per_agent}


def build_overview() -> dict[str, Any]:
    """4-block control-plane overview: registry / health / queue / approvals.

    Each block is independently fail-degraded (`_safe`) — a broken agent profile, a
    dead integration probe, or a corrupt approvals db can only empty ITS OWN block,
    never take down the other three (phase acceptance criterion)."""
    return {
        "v": CONTRACT_VERSION,
        "registry": _safe(_registry_block, {"agents": []}, "registry"),
        "health": _safe(
            _health_block, {"coordinator_ok": False, "integrations": []}, "health"
        ),
        "queue": _safe(_queue_block, {"depth": 0, "running": 0, "stalled": 0}, "queue"),
        "approvals": _safe(
            _approvals_block, {"pending_total": 0, "pending_by_agent": {}}, "approvals"
        ),
    }
