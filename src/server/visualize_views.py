"""Read-only view assembly for the M4 visualization JSON API (v2 M4-S1).

Each view reads one per-agent data source and projects it to an explicit NON-PII
allowlist — mirroring the `summarize_node` discipline (`src/server/sse_events.py:17`):
select fields, never echo raw state. Stores are opened-then-closed (fd-leak discipline,
like `agent_views._pending_count`). Views are READ-ONLY by construction: no `gw.approve`,
no `record_cost`, no `check_allowed`, no write path — the Action Gateway is untouched.

`memory_view` is INTERNAL-ONLY, gated by an explicit `audience` arg: `external` returns
nothing (the P5 red line — a typo must not silently leak remembered facts).
"""

from __future__ import annotations

from typing import Any

from src.actions.approval_store import ApprovalStore
from src.audit.audit_log import AuditLog
from src.llm.budget_tracker import BudgetTracker
from src.profile.loader import load_profile
from src.runtime.agent_paths import agent_data_dir
from src.runtime.registry import load_registry
from src.runtime.run_event import read_run_events

# Reuse the router-shared 404 sentinel so all server routes map unknown ids consistently.
from src.server.agent_views import UnknownAgentError

_AUDIT_LIMIT_MAX = 200
_RUN_LIMIT_MAX = 500
# Run-event fields safe to expose (the run log carries no persona/project text).
# v8 M23: `auto_approved` (a bool flag) rides the run event so the "đã tự duyệt" view can
# show auto-delivered scheduled reports. report_summary stays EXCLUDED (M22 B3).
_RUN_FIELDS = ("ts", "kind", "audience", "status", "cost_usd", "delivered", "auto_approved")
# Audit fields safe to expose (already redacted at write time; still select, don't echo).
# `rationale`/`result_summary` stay EXCLUDED (a verified privacy decision) — the trust-ladder
# "đã tự duyệt" view reads the run-event auto_approved flag instead, not the audit rationale.
_AUDIT_FIELDS = ("timestamp", "action_type", "tool", "verdict", "reason", "actor")


def _require_agent(agent_id: str) -> None:
    """Raise UnknownAgentError (→ 404) if the id is not a registered agent."""
    if agent_id not in {e.id for e in load_registry()}:
        raise UnknownAgentError(agent_id)


def _settings(agent_id: str):
    return load_profile(agent_id, data_dir=agent_data_dir(agent_id)).settings


def runs_view(agent_id: str, *, limit: int = 100) -> dict[str, Any]:
    """Run timeline: newest-first run-events projected to the non-PII allowlist."""
    _require_agent(agent_id)
    clamp = max(1, min(limit, _RUN_LIMIT_MAX))
    events = read_run_events(agent_id, limit=clamp)
    return {"agent_id": agent_id, "runs": [_pick(e, _RUN_FIELDS) for e in events]}


def cost_view(agent_id: str) -> dict[str, Any]:
    """Monthly cost series (last 12 months) + cap/warn-ratio. Side-effect-free."""
    _require_agent(agent_id)
    settings = _settings(agent_id)
    tracker = BudgetTracker(settings)
    return {
        "agent_id": agent_id,
        "series": tracker.monthly_series(months=12),
        "cap": settings.monthly_budget_usd,
        "warn_ratio": settings.budget_warn_ratio,
        "spent_this_month": tracker.spent_this_month(),
    }


def memory_view(agent_id: str, *, audience: str = "internal") -> dict[str, Any]:
    """Remembered facts — INTERNAL-ONLY. `audience != 'internal'` ⇒ no facts (P5 red line)."""
    _require_agent(agent_id)
    if audience != "internal":
        # Do not leak remembered state to an external-audience read. Return empty, not 500.
        # Gate is BEFORE building the store, so external never even opens a connection.
        return {"agent_id": agent_id, "facts": [], "internal_only": True}
    from src.agent.memory_node import _NAMESPACE_KIND
    from src.agent.store import get_store

    settings = _settings(agent_id)
    store = get_store(settings)
    try:
        items = store.search((agent_id, _NAMESPACE_KIND))
        facts = [_fact(item) for item in items]
    finally:
        # The long-lived server must not leak a per-request Postgres connection (the
        # opt-in PostgresStore wraps a raw psycopg conn). InMemoryStore has no conn → no-op.
        _close_store(store)
    return {"agent_id": agent_id, "facts": facts, "internal_only": True}


def _close_store(store: Any) -> None:
    """Close a Store's underlying connection if it has one (Postgres); no-op otherwise."""
    conn = getattr(store, "conn", None)
    if conn is not None and hasattr(conn, "close"):
        conn.close()


def automation_view(agent_id: str) -> dict[str, Any]:
    """Pending Lớp B proposals (incl. D3 workflow proposals); action summarized, not raw."""
    _require_agent(agent_id)
    settings = _settings(agent_id)
    store = ApprovalStore(settings.data_dir / "approvals.db")
    try:
        pending = store.list_pending()
    finally:
        store.close()
    return {
        "agent_id": agent_id,
        "pending": [
            {
                "id": p.id,
                "reason": p.reason,
                "status": p.status,
                "created_at": p.created_at,
                "action_summary": _action_summary(p.action),
            }
            for p in pending
        ],
    }


def audit_view(agent_id: str, *, limit: int = 50) -> dict[str, Any]:
    """Guardrail events: aggregated verdict counts + recent (allowlisted) rows."""
    _require_agent(agent_id)
    path = agent_data_dir(agent_id) / "audit" / "audit.jsonl"
    log = AuditLog(path)
    all_rows = log.query()  # already-redacted records
    counts: dict[str, int] = {}
    for row in all_rows:
        verdict = str(row.get("verdict", "?"))
        counts[verdict] = counts.get(verdict, 0) + 1
    clamp = max(1, min(limit, _AUDIT_LIMIT_MAX))
    recent = [_pick(r, _AUDIT_FIELDS) for r in all_rows[:clamp]]  # query() is newest-first
    return {"agent_id": agent_id, "counts": counts, "recent": recent}


# --- projection helpers (allowlist-in, drop everything else) ---


def _pick(record: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {k: record.get(k) for k in fields}


def _fact(item: Any) -> dict[str, Any]:
    """Project a Store item to a short fact allowlist (fact text + ts), nothing else.

    The memory node stores `{"fact": <text>, "ts": <iso>}` (memory_node.remember), so the
    allowlist is exactly those plus the item key.
    """
    value = getattr(item, "value", {}) or {}
    return {
        "fact": value.get("fact"),
        "ts": value.get("ts"),
        "key": getattr(item, "key", None),
    }


def _action_summary(action: dict[str, Any]) -> str:
    """A short label for a proposed action — type/server/tool only, NOT the raw args."""
    parts = [str(action.get("type", "?"))]
    if action.get("server"):
        parts.append(str(action["server"]))
    if action.get("tool"):
        parts.append(str(action["tool"]))
    return ":".join(parts)
