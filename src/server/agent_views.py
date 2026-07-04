"""Read-only view assembly for the agent routes (v2 M2-P6).

Pure data assembly over the existing per-agent primitives — the routers stay thin.
Everything keys off `agent_data_dir(id)` (same store the worker/mpm path uses), so the
views read the migrated per-agent budget / approvals / run-event log.

No graph is built and no LLM is called here, so these views need no API key and do no
network I/O beyond reading local per-agent files (+ profile.yaml / .env via load_profile).
"""

from __future__ import annotations

from src.actions.approval_store import ApprovalStore
from src.llm.budget_tracker import BudgetTracker
from src.profile.loader import load_profile
from src.runtime.agent_paths import agent_data_dir
from src.runtime.registry import load_registry
from src.runtime.run_event import read_last_run_event


class UnknownAgentError(LookupError):
    """Raised when an agent id is not in the registry (router maps to 404)."""


def _registry_enabled() -> dict[str, bool]:
    return {e.id: e.enabled for e in load_registry()}


#: Run-event fields safe to expose to a client. `report_summary` (v8 M22) holds report
#: CONTENT and is deliberately EXCLUDED — it is for the internal fleet roll-up only, never
#: the status API (red-team B3: the raw event must not leak the last report's prose).
_LAST_RUN_PUBLIC_FIELDS = ("ts", "agent_id", "kind", "audience", "status", "cost_usd",
                           "delivered")


def _public_last_run(agent_id: str) -> dict | None:
    """The agent's last run-event with only the non-sensitive fields (drops report_summary)."""
    ev = read_last_run_event(agent_id)
    if ev is None:
        return None
    return {k: ev[k] for k in _LAST_RUN_PUBLIC_FIELDS if k in ev}


def list_agents() -> list[dict]:
    """One entry per registry agent: id, name, enabled, last_run.

    `enabled` is registry-enabled AND profile-enabled (mirrors the service gate). The
    list view carries no PII — `last_run` is the run-event dict (agent_id/kind/audience/
    status/cost_usd/delivered/ts), all non-sensitive. The M22 `report_summary` field is
    filtered out here (it is internal roll-up content, not for the status API).
    """
    out: list[dict] = []
    for entry in load_registry():
        # One broken profile must not 500 the whole list (mirrors the CLI `run_list`
        # which degrades a bad profile rather than failing the aggregation).
        try:
            loaded = load_profile(entry.id, data_dir=agent_data_dir(entry.id))
            name, prof_enabled = loaded.name, loaded.enabled
        except (FileNotFoundError, RuntimeError) as exc:
            name, prof_enabled = f"<error: {exc}>", False
        out.append(
            {
                "id": entry.id,
                "name": name,
                "enabled": bool(entry.enabled and prof_enabled),
                "last_run": _public_last_run(entry.id),
            }
        )
    return out


def agent_status(agent_id: str) -> dict:
    """Full status for one agent: enabled, last_run, budget, pending-approvals count.

    Raises UnknownAgentError (→ 404) if the id is not registered.
    """
    reg = _registry_enabled()  # one registry read; also the membership check
    if agent_id not in reg:
        raise UnknownAgentError(agent_id)
    loaded = load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    enabled = bool(reg[agent_id] and loaded.enabled)

    spent = BudgetTracker(loaded.settings).spent_this_month()
    cap = loaded.settings.monthly_budget_usd
    budget = {"spent": spent, "cap": cap, "ratio": (spent / cap if cap > 0 else 0.0)}

    return {
        "id": agent_id,
        "name": loaded.name,
        "enabled": enabled,
        "last_run": _public_last_run(agent_id),
        "budget": budget,
        "pending_approvals": _pending_count(loaded.settings.data_dir),
    }


def _pending_count(data_dir) -> int:
    """Count pending Lớp B approvals without standing up a full ActionGateway.

    Opens only the ApprovalStore (one SQLite connection) and CLOSES it — the web
    service is long-lived, so it must not leak the gateway's dedup + approval
    connections on every /status request.
    """
    store = ApprovalStore(data_dir / "approvals.db")
    try:
        return len(store.list_pending())
    finally:
        store.close()
