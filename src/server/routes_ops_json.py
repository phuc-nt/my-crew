"""JSON ops API for the React dashboard (v2 M4-S4) — approvals + config.

JSON siblings of the htmx approve/reject/config routes. They call the IDENTICAL gateway
and profile-editor functions — only the response shape changes (JSON, not Jinja2 partials).
The htmx routes stay live in parallel until S5; this adds no new write logic.

RED LINE (approve): the approve handler runs `gw.approve(approval_id, handler=lambda a:
dispatch_approved_action(a, loaded.config))` and nothing else for the post — the SAME real
path as the CLI and the htmx UI. It does NOT build the action client-side, call any adapter
directly, or skip the gateway. Lớp A hard-deny + audit + dedup apply via the gateway.
MEMORY.md has NO write route (agent self-writes it).
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from src.actions.action_gateway import HardBlockedError
from src.server import profile_editor
from src.server.ops_helpers import build_gateway, require_agent

router = APIRouter(prefix="/api/agents", tags=["ops"])

_EDITABLE_MD = {"soul": "SOUL.md", "project": "PROJECT.md"}


def _pending_json(loaded) -> list[dict]:
    gw = build_gateway(loaded)
    try:
        return [
            {
                "id": p.id,
                "reason": p.reason,
                "status": p.status,
                "created_at": p.created_at,
                "action": p.action,  # already redacted at enqueue; shown for the confirm step
            }
            for p in gw.pending_approvals()
        ]
    finally:
        gw.close()


@router.get("/{agent_id}/approvals")
def list_approvals(agent_id: str) -> dict:
    """Pending Lớp B approvals (already-redacted actions) for the confirm step."""
    loaded = require_agent(agent_id)
    return {"agent_id": agent_id, "pending": _pending_json(loaded)}


@router.post("/{agent_id}/approvals/{approval_id}/approve")
def approve(agent_id: str, approval_id: int) -> dict:
    """Run the approved action for REAL — same path as `mpm agent approve` / the htmx UI."""
    loaded = require_agent(agent_id)
    gw = build_gateway(loaded)
    try:
        # Agent-bound dispatch (v31 P2): native types (schedule_update) get their identity
        # closure from THIS route's agent_id; mcp/email fall through to the shared dispatch.
        from src.actions.approved_dispatch import make_agent_bound_dispatch

        gw.approve(approval_id, handler=make_agent_bound_dispatch(agent_id, loaded.config))
    except ValueError as exc:  # unknown / already-consumed id
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except HardBlockedError as exc:  # Lớp A — never approvable
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except RuntimeError as exc:  # post failed — gateway reverts to pending; retryable
        raise HTTPException(
            status_code=502, detail=f"post failed (still pending, retry): {exc}"
        ) from None
    finally:
        gw.close()
    return {"agent_id": agent_id, "approved": approval_id, "pending": _pending_json(loaded)}


@router.post("/{agent_id}/approvals/{approval_id}/reject")
def reject(agent_id: str, approval_id: int) -> dict:
    """Reject (audit, no post)."""
    loaded = require_agent(agent_id)
    gw = build_gateway(loaded)
    try:
        gw.reject(approval_id)
    finally:
        gw.close()
    return {"agent_id": agent_id, "rejected": approval_id, "pending": _pending_json(loaded)}


# --- config (validate→atomic-replace; MEMORY.md read-only) ---


@router.get("/{agent_id}/config")
def get_config(agent_id: str) -> dict:
    """The 4 profile files (yaml/soul/project/memory) as text; memory is read-only client-side."""
    require_agent(agent_id)
    return {"agent_id": agent_id, "files": profile_editor.read_profile_files(agent_id)}


@router.post("/{agent_id}/config/profile")
def save_profile(agent_id: str, text: str = Body(..., embed=True)) -> dict:
    """Save profile.yaml: validate in memory → atomic replace. Bad edit → 400, original kept."""
    import yaml

    require_agent(agent_id)
    try:
        profile_editor.save_profile_yaml(agent_id, text)
    except (ValueError, RuntimeError, yaml.YAMLError) as exc:
        # Malformed YAML (YAMLError), a non-mapping (ValueError), or a bad-config build
        # (RuntimeError) all mean "bad edit" → 400 with the exact message; original kept
        # (save_profile_yaml validates BEFORE the atomic write, so nothing was written).
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"agent_id": agent_id, "saved": "profile.yaml"}


@router.post("/{agent_id}/config/{md}")
def save_md(agent_id: str, md: str, text: str = Body(..., embed=True)) -> dict:
    """Save SOUL.md / PROJECT.md. Any other name (incl. memory) → 400 (no write)."""
    require_agent(agent_id)
    filename = _EDITABLE_MD.get(md)
    if filename is None:
        raise HTTPException(
            status_code=400, detail=f"{md!r} is not editable (only soul / project)."
        )
    profile_editor.save_markdown(agent_id, filename, text)
    return {"agent_id": agent_id, "saved": filename}
