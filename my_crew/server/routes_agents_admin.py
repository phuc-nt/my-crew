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

from my_crew.runtime.registry_edit import (
    UnknownRegistryAgentError,
    append_registry,
    remove_registry_entry,
    set_registry_enabled,
)
from my_crew.server import agent_create, integration_health

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


@router.get("/agents/unregistered")
def get_unregistered_profiles() -> dict:
    """v18: profile dirs present on disk but absent from the registry — the "profiles
    exist yet the office has nobody" trap (a registry wipe/revert, or a scaffold that
    never registered). Per-profile validation degrades (one broken profile.yaml must
    not 500 the list); `templates/` is a prefill library, never a candidate."""
    from my_crew.profile.loader import _PROFILES_DIR, load_profile
    from my_crew.runtime.registry import load_registry

    registered = {e.id for e in load_registry()}
    out = []
    for d in sorted(_PROFILES_DIR.iterdir() if _PROFILES_DIR.is_dir() else []):
        if not d.is_dir() or d.name == "templates" or d.name in registered:
            continue
        if not (d / "profile.yaml").exists():
            continue  # scaffolding leftovers without a profile are not agents
        try:
            loaded = load_profile(d.name)
            out.append({"id": d.name, "name": loaded.name or d.name,
                        "domain": getattr(loaded, "domain", ""), "valid": True})
        except Exception as exc:  # noqa: BLE001 — red-team M2: yaml/Validation/anything
            out.append({"id": d.name, "name": d.name, "domain": "",
                        "valid": False, "error": str(exc)[:160]})
    return {"profiles": out}


@router.post("/agents/{agent_id}/register", status_code=201)
def post_register_existing(agent_id: str) -> dict:
    """v18: register-ONLY — append an EXISTING profile dir to the registry (the create
    wizard 409s on an existing dir; this is the recovery path). Profile must load
    cleanly first (never register an agent the service cannot start)."""
    from my_crew.profile.loader import _PROFILES_DIR, load_profile
    from my_crew.runtime.agent_paths import _validate_agent_id
    from my_crew.runtime.registry import _REGISTRY_PATH, load_registry

    try:
        agent_id = _validate_agent_id(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if not (_PROFILES_DIR / agent_id / "profile.yaml").exists():
        raise HTTPException(status_code=404, detail=f"profiles/{agent_id}/ không tồn tại")
    if any(e.id == agent_id for e in load_registry()):
        raise HTTPException(status_code=409, detail=f"{agent_id} đã có trong đội")
    try:
        load_profile(agent_id)
    except Exception as exc:  # noqa: BLE001 — broken profile must not be registered
        raise HTTPException(status_code=400,
                            detail=f"hồ sơ lỗi, chưa thể thêm: {str(exc)[:160]}") from None
    try:
        append_registry(_REGISTRY_PATH, agent_id)
    except Exception as exc:  # noqa: BLE001 — red-team M3: a lost race (duplicate) or
        # validate-before-replace failure surfaces as a clean conflict, never a 500.
        raise HTTPException(status_code=409, detail=str(exc)[:160]) from None
    return {"id": agent_id, "registered": True}


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
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir

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

    from my_crew.runtime.agent_state_reader import read_all_agent_states, team_alerts

    now = time.time()
    if _alerts_cache["payload"] is not None and now - _alerts_cache["at"] < _ALERTS_CACHE_TTL_S:
        return _alerts_cache["payload"]
    payload = {"alerts": team_alerts(read_all_agent_states())}
    _alerts_cache["at"], _alerts_cache["payload"] = now, payload
    return payload
