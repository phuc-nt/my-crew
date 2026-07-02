"""Agent admin routes (v3 M7): packs list, create wizard, lifecycle, integration health.

The write surfaces here mutate CONFIG (profiles/ + registry.yaml) — not external
systems — so they do not route through the Action Gateway (which guards Slack/Jira/…
mutations). They reuse the validate-before-replace primitives (`agent_create`,
`registry_edit`) so a bad request can never leave a corrupt registry or a half-created
agent. Localhost-only + no-auth posture unchanged (see app.py).

DELETE removes ONLY the registry entry; profiles/<id>/ and .data/agents/<id>/ stay on
disk as an archive (audit history must survive an agent's removal). `default` cannot be
deleted — it is the v1 backward-compat safety net (disable it instead).
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from src.runtime.registry_edit import (
    UnknownRegistryAgentError,
    remove_registry_entry,
    set_registry_enabled,
)
from src.server import agent_create, integration_health

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/packs")
def get_packs() -> dict:
    """Installed domain packs (id/name/report_kinds/servers) for the wizard's picker."""
    return {"packs": agent_create.list_packs()}


@router.post("/agents/create", status_code=201)
async def post_create_agent(request: Request) -> dict:
    """Create an agent from the wizard spec — same scaffold path as `mpm agent register`."""
    try:
        spec = await request.json()
    except Exception:  # noqa: BLE001 — any non-JSON body is a client error
        raise HTTPException(status_code=400, detail="body must be a JSON object") from None
    if not isinstance(spec, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    try:
        created = agent_create.create_agent(spec)
    except agent_create.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except agent_create.ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"created": created}


@router.patch("/agents/{agent_id}/enabled")
def patch_agent_enabled(agent_id: str, enabled: bool = Body(..., embed=True)) -> dict:
    """Pause/resume: flip the registry master switch (validate-before-replace).

    `effective_enabled` = registry AND profile.yaml `enabled` — the value the service
    gate actually uses. A resume that the profile still vetoes must not look successful
    to the operator, so the response says which gate is holding the agent down.
    """
    try:
        set_registry_enabled(None, agent_id, enabled)
    except UnknownRegistryAgentError:
        raise HTTPException(status_code=404, detail=f"unknown agent {agent_id!r}") from None
    return {
        "agent_id": agent_id,
        "enabled": enabled,
        "effective_enabled": enabled and _profile_enabled(agent_id),
    }


def _profile_enabled(agent_id: str) -> bool:
    """profile.yaml's own `enabled` gate (broken profile → False, never a 500)."""
    from src.profile.loader import load_profile
    from src.runtime.agent_paths import agent_data_dir

    try:
        return bool(load_profile(agent_id, data_dir=agent_data_dir(agent_id)).enabled)
    except (FileNotFoundError, RuntimeError):
        return False


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str) -> dict:
    """Remove the registry entry (profile + data dirs kept on disk as archive)."""
    if agent_id == "default":
        raise HTTPException(
            status_code=400,
            detail="'default' is the v1 backward-compat agent — disable it instead of deleting.",
        )
    try:
        remove_registry_entry(None, agent_id)
    except UnknownRegistryAgentError:
        raise HTTPException(status_code=404, detail=f"unknown agent {agent_id!r}") from None
    return {"agent_id": agent_id, "deleted": True, "profile_dir_kept": True}


@router.get("/health/integrations")
def get_integration_health() -> dict:
    """Per-integration ok/hint (no secret values) — the 'what is broken?' panel."""
    return integration_health.integration_checks()


_ALERTS_CACHE_TTL_S = 30.0
_alerts_cache: dict = {"at": 0.0, "payload": None}


@router.get("/team/alerts")
def get_team_alerts() -> dict:
    """Deterministic fleet alerts (M8 S5): budget near cap, stuck approvals, deny spikes.

    Read-only over every agent's local state via the generic accessor — same data the
    admin pack's reports aggregate, exposed raw for the Team view banner. Cached 30s
    per process (same posture as /api/health/integrations): the scan loads every
    profile + audit tail, so a mounting Team view must not re-run it per render.
    """
    import time

    from src.runtime.agent_state_reader import read_all_agent_states, team_alerts

    now = time.time()
    if _alerts_cache["payload"] is not None and now - _alerts_cache["at"] < _ALERTS_CACHE_TTL_S:
        return _alerts_cache["payload"]
    payload = {"alerts": team_alerts(read_all_agent_states())}
    _alerts_cache["at"], _alerts_cache["payload"] = now, payload
    return payload
