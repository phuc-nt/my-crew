"""Read-only view assembly for the agent routes (v2 M2-P6).

Pure data assembly over the existing per-agent primitives — the routers stay thin.
Everything keys off `agent_data_dir(id)` (same store the worker/mpm path uses), so the
views read the migrated per-agent budget / approvals / run-event log.

No graph is built and no LLM is called here, so these views need no API key and do no
network I/O beyond reading local per-agent files (+ profile.yaml / .env via load_profile).
"""

from __future__ import annotations

from my_crew.actions.approval_store import ApprovalStore
from my_crew.llm.budget_tracker import BudgetTracker
from my_crew.profile.loader import load_profile
from my_crew.runtime.agent_paths import agent_data_dir
from my_crew.runtime.registry import load_registry
from my_crew.runtime.run_event import read_last_run_event


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


def _report_kinds_for_domain(domain: str) -> list[str]:
    """The report kinds this agent's OWN pack serves (v10 M25, additive for the web
    Trigger form). The Trigger UI hardcoded PM's four kinds, so an hr/admin agent was
    offered the wrong set; this exposes the correct per-agent kinds. A broken/unknown
    pack degrades to an empty list rather than 500-ing the agent list (mirrors the
    all_report_kinds() union which skips broken packs).

    Loading a pack re-executes its modules (no cache), so callers iterating agents should
    memoize per-domain — see list_agents()."""
    import logging

    from my_crew.packs.registry import PackRegistry

    try:
        return sorted(PackRegistry().load(domain).report_kinds)
    except Exception:  # noqa: BLE001 — an unknown/broken domain must not break the list
        # A ValueError here is the expected "unknown domain" case; an import/exec failure is
        # not — log so a genuinely broken pack leaves a breadcrumb instead of silently
        # showing no kinds.
        logging.getLogger(__name__).warning(
            "report_kinds unavailable for domain %r", domain, exc_info=True
        )
        return []


def list_agents() -> list[dict]:
    """One entry per registry agent: id, name, enabled, last_run.

    `enabled` is registry-enabled AND profile-enabled (mirrors the service gate). The
    list view carries no PII — `last_run` is the run-event dict (agent_id/kind/audience/
    status/cost_usd/delivered/ts), all non-sensitive. The M22 `report_summary` field is
    filtered out here (it is internal roll-up content, not for the status API).
    """
    out: list[dict] = []
    # Loading a pack re-executes its modules (registry has no cache), so memoize per DISTINCT
    # domain — a fleet of N pm agents then loads the pm pack once, not N times.
    kinds_by_domain: dict[str, list[str]] = {}

    def _kinds_for(domain: str) -> list[str]:
        if domain not in kinds_by_domain:
            kinds_by_domain[domain] = _report_kinds_for_domain(domain)
        return kinds_by_domain[domain]

    for entry in load_registry():
        # One broken profile must not 500 the whole list (mirrors the CLI `run_list`
        # which degrades a bad profile rather than failing the aggregation).
        try:
            loaded = load_profile(entry.id, data_dir=agent_data_dir(entry.id))
            name, prof_enabled = loaded.name, loaded.enabled
            report_kinds = _kinds_for(loaded.domain)
            # v30: EFFECTIVE trust mode (yaml override merged over env/default) — the FE
            # must never re-derive this from raw yaml.
            trust_mode = loaded.settings.trust_mode
        except (FileNotFoundError, RuntimeError) as exc:
            name, prof_enabled, report_kinds = f"<error: {exc}>", False, []
            trust_mode = "guarded"  # broken profile: show the conservative mode
        out.append(
            {
                "id": entry.id,
                "name": name,
                "enabled": bool(entry.enabled and prof_enabled),
                "last_run": _public_last_run(entry.id),
                # v10 M25: the report kinds this agent's pack serves (drives the Trigger form).
                "report_kinds": report_kinds,
                "trust_mode": trust_mode,
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
        "trust_mode": loaded.settings.trust_mode,
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
