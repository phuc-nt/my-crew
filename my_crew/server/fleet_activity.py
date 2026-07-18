"""Fleet-wide activity aggregation — the CEO's "what did the company do" read (v31 P1).

Merges three already-bounded, per-agent or fleet-shared data sources into one
newest-first timeline, projecting each row to an explicit NON-PII allowlist
(the `visualize_views` discipline: select fields, never echo raw state):

- per-agent `audit/audit.jsonl` — Action Gateway decisions (redacted at write time)
- per-agent `runs.jsonl` — worker run outcomes (`_RUN_FIELDS` allowlist)
- fleet-shared `captures.sqlite3` — team-step attempt telemetry

READ-ONLY by construction: no gateway, no writes. A broken agent (unreadable
profile/data) degrades to a `skipped` entry — one bad profile must not 500 the
fleet view. Every per-agent read is bounded BEFORE the merge, so an N-agent scan
stays O(N × limit) rows, never an unbounded history.

INTERNAL-ONLY surface: consumed by the dashboard (operator) and the ops-chat
summarizer. Nothing here routes to an external audience.
"""

from __future__ import annotations

from typing import Any

from my_crew.audit.audit_log import AuditLog
from my_crew.runtime.agent_paths import agent_data_dir
from my_crew.runtime.registry import load_registry
from my_crew.runtime.run_event import read_run_events
from my_crew.server.agent_views import UnknownAgentError

# Reuse the visualize allowlists so the fleet view can never expose MORE than the
# per-agent views do (single source of truth for what is safe to project).
from my_crew.server.visualize_views import _AUDIT_FIELDS, _RUN_FIELDS

_LIMIT_MAX = 200
#: Capture columns safe to expose — ids/engine/outcome only, never error text
#: (a capture `error` carries raw exception strings from third-party tools).
_CAPTURE_FIELDS = ("task_id", "step_id", "engine", "status", "step_type", "cost_usd")


def fleet_activity(
    *,
    limit: int = 100,
    since: str | None = None,
    agent: str | None = None,
    verdict: str | None = None,
) -> dict[str, Any]:
    """One merged newest-first activity list across every registry agent.

    `since` is an ISO date/datetime prefix (rows with ts >= it). `agent` restricts
    to one registered agent (unknown ⇒ UnknownAgentError → 404 at the route).
    `verdict` filters audit rows AND drops the other sources (a verdict question
    is an audit question). Each item carries `ts`/`agent_id`/`source` plus only
    its source's allowlisted fields.
    """
    clamp = max(1, min(int(limit), _LIMIT_MAX))
    registry_ids = [e.id for e in load_registry()]
    if agent is not None:
        if agent not in registry_ids:
            raise UnknownAgentError(agent)
        registry_ids = [agent]

    items: list[dict[str, Any]] = []
    skipped: list[str] = []
    for agent_id in registry_ids:
        try:
            items.extend(_audit_items(agent_id, limit=clamp, since=since, verdict=verdict))
            if verdict is None:
                items.extend(_run_items(agent_id, limit=clamp, since=since))
        except Exception:  # noqa: BLE001 — one broken agent must not 500 the fleet view
            skipped.append(agent_id)
    if verdict is None:
        items.extend(_capture_items(limit=clamp, since=since, agent_id=agent))

    items.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    return {"items": items[:clamp], "agents": registry_ids, "skipped": skipped}


def _audit_items(
    agent_id: str, *, limit: int, since: str | None, verdict: str | None
) -> list[dict[str, Any]]:
    log = AuditLog(agent_data_dir(agent_id) / "audit" / "audit.jsonl")
    rows = log.query(verdict=verdict, since=since, limit=limit)
    out = []
    for row in rows:
        item = {k: row.get(k) for k in _AUDIT_FIELDS if k != "timestamp"}
        item.update({"ts": row.get("timestamp"), "agent_id": agent_id, "source": "audit"})
        out.append(item)
    return out


def _run_items(agent_id: str, *, limit: int, since: str | None) -> list[dict[str, Any]]:
    events = read_run_events(agent_id, limit=limit)
    out = []
    for ev in events:
        ts = str(ev.get("ts") or "")
        if since and ts < since:
            continue
        item = {k: ev.get(k) for k in _RUN_FIELDS if k != "ts"}
        item.update({"ts": ev.get("ts"), "agent_id": agent_id, "source": "run"})
        out.append(item)
    return out


def _capture_items(
    *, limit: int, since: str | None, agent_id: str | None
) -> list[dict[str, Any]]:
    """Fleet-shared captures DB read; absent file ⇒ no rows (don't mint an empty DB)."""
    from my_crew.runtime.capture_store import CaptureStore
    from my_crew.runtime.team_task_paths import capture_db_path

    path = capture_db_path()
    if not path.exists():
        return []
    store = CaptureStore(path)
    try:
        rows = store.list_recent(limit=limit, since=since, agent_id=agent_id)
    finally:
        store.close()
    out = []
    for row in rows:
        item = {k: row.get(k) for k in _CAPTURE_FIELDS}
        item.update({"ts": row.get("ts"), "agent_id": row.get("agent_id"), "source": "capture"})
        out.append(item)
    return out
