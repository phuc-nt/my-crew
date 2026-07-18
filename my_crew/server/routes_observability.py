"""Read-only observability routes (dual-lens P3). STRICTLY read-only — three GETs,
no Gateway involvement (nothing here mutates anything):

- `GET /api/budget` — fleet budget: per-agent month spend vs cap + totals. Same
  computation `agent_views.agent_status` does for one agent, summed over the registry.
- `GET /api/captures` (+ `/api/captures/{attempt_id}`) — the v26 per-step-attempt
  telemetry rows (tokens, cost + source, engine, duration) for the Captures explorer.
- `GET /api/search` — the v33 FTS5 history index, UI search box only. The index module
  itself escapes the query into quoted terms (MATCH syntax is data, not operators);
  this route only bounds the inputs.

All three sit behind the app's AuthMiddleware like every other /api route and degrade
to empty payloads when a store file does not exist yet (fresh install ≠ 500).
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException

from my_crew.llm.budget_tracker import BudgetTracker
from my_crew.profile.loader import load_profile
from my_crew.runtime.capture_store import CaptureStore
from my_crew.runtime.history_search_index import HistorySearchIndex
from my_crew.runtime.registry import load_registry
from my_crew.runtime.team_task_paths import capture_db_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["observability"])

_SEARCH_QUERY_MAX_CHARS = 200

# Sweep throttle (review M2): a sweep re-reads every agent's audit log before the
# watermark filters rows, so per-keystroke sweeps grow O(total audit bytes). One sweep
# per interval keeps results fresh enough for a human search box.
_SWEEP_MIN_INTERVAL_S = 30.0
_last_sweep_at = 0.0


@router.get("/budget")
def fleet_budget() -> dict:
    """Per-agent month spend vs cap + fleet totals. Registry entries whose profile is
    missing are skipped (same resilience rule as the service loop — a half-created
    agent must not 500 the whole gauge)."""
    agents: list[dict] = []
    for entry in load_registry():
        try:
            loaded = load_profile(entry.id)
        except (FileNotFoundError, RuntimeError) as exc:
            logger.warning("budget: skipping agent %r: %s", entry.id, exc)
            continue
        spent = BudgetTracker(loaded.settings).spent_this_month()
        cap = loaded.settings.monthly_budget_usd
        agents.append(
            {
                "agent_id": entry.id,
                "spent_usd": round(spent, 6),
                "cap_usd": cap,
                "ratio": (spent / cap) if cap > 0 else 0.0,
            }
        )
    total_spent = sum(a["spent_usd"] for a in agents)
    total_cap = sum(a["cap_usd"] for a in agents)
    return {
        "agents": agents,
        "total_spent_usd": round(total_spent, 6),
        "total_cap_usd": total_cap,
        "ratio": (total_spent / total_cap) if total_cap > 0 else 0.0,
    }


@router.get("/captures")
def list_captures(
    task_id: str = "", agent: str = "", since: str = "", limit: int = 100
) -> dict:
    """Capture rows, newest-first. `task_id` filter uses the store's per-task read
    (chronological, the debug order); otherwise `list_recent` with its own 500-row
    clamp. A store file that does not exist yet returns an empty list."""
    path = capture_db_path()
    if not path.exists():
        return {"captures": []}
    store = CaptureStore(path)
    try:
        if task_id:
            rows = store.list_for_task(task_id)
        else:
            rows = store.list_recent(
                limit=limit, since=since or None, agent_id=agent or None
            )
    finally:
        store.close()
    return {"captures": rows}


@router.get("/captures/{attempt_id}")
def capture_detail(attempt_id: str) -> dict:
    path = capture_db_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="capture not found")
    store = CaptureStore(path)
    try:
        row = store.get(attempt_id)
    finally:
        store.close()
    if row is None:
        raise HTTPException(status_code=404, detail="capture not found")
    return row


@router.get("/search")
def search_history(q: str = "", agent: str = "", days: int = 0, limit: int = 8) -> dict:
    """FTS5 history search for the high-mode UI box. Sweep-then-search mirrors the
    ops-chat catalog's own usage so results include the newest events."""
    global _last_sweep_at
    query = q.strip()[:_SEARCH_QUERY_MAX_CHARS]
    if not query:
        return {"hits": []}
    idx = HistorySearchIndex()
    try:
        now = time.monotonic()
        if now - _last_sweep_at >= _SWEEP_MIN_INTERVAL_S:
            _last_sweep_at = now
            idx.sweep()
        hits = idx.search(query, days=max(0, days), agent=agent, limit=max(1, min(limit, 25)))
    finally:
        idx.close()
    return {"hits": hits}
