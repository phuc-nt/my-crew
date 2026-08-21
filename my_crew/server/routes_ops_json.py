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

from my_crew.actions.action_gateway import HardBlockedError
from my_crew.actions.approval_rule_store import SCOPE_ALWAYS, SCOPE_DENY
from my_crew.server import profile_editor
from my_crew.server.ops_helpers import build_gateway, require_agent

router = APIRouter(prefix="/api/agents", tags=["ops"])

#: Scope tokens the web dropdown may send with an approve/reject decision — the SAME
#: vocabulary `ops_approvals.py`'s chat path teaches a standing rule from
#: (`SCOPE_ALWAYS`/`SCOPE_DENY`), plus "once" for the plain one-off decision (no rule
#: learned). A bounded enum, not free text (H4/red-team): a typo here can never
#: silently escalate a one-off decision into a permanent rule the way a parsed
#: free-text field could.
_SCOPE_ONCE = "once"
_VALID_SCOPES = frozenset({_SCOPE_ONCE, SCOPE_ALWAYS, SCOPE_DENY})

#: Fleet-wide approvals index. Separate router because the per-agent routes above are
#: all mounted under `/api/agents/{agent_id}` and this one is deliberately NOT scoped to
#: an agent — it answers "what is waiting on me anywhere".
approvals_router = APIRouter(prefix="/api/approvals", tags=["ops"])

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


@approvals_router.get("/pending")
def pending_index() -> dict:
    """Every pending approval across the fleet, each row tagged with its owning agent.

    Approve/reject stay per-agent routes, so `agent_id` on the row is what lets a
    caller build the action URL. A per-agent load failure is skipped rather than
    fatal: one broken profile must not blank a queue whose other rows are actionable.

    Rows come back OLDEST FIRST across the whole fleet. Grouping by the registry walk
    put every row of the alphabetically-first agent on top, so a request left hanging
    since yesterday sat below rows that arrived minutes ago — and the reader works down
    from the top. `(agent_id, id)` breaks ties so reloading the page never shuffles
    rows that share a timestamp.
    """
    from my_crew.server import agent_views

    pending: list[dict] = []
    for entry in agent_views.load_registry():
        try:
            loaded = require_agent(entry.id)
            rows = _pending_json(loaded)
        except Exception:  # unreadable profile / missing store — other agents still count
            continue
        pending.extend({"agent_id": entry.id, **row} for row in rows)
    pending.sort(key=lambda row: (row["created_at"], row["agent_id"], row["id"]))
    return {"pending": pending, "count": len(pending)}


def _validate_scope(scope: str) -> str:
    """`once` (default, no rule learned) or the two standing scopes — 400 on anything
    else, so a client bug sending an unrecognized word fails loudly instead of the
    chat path's forgiving "unknown ⇒ once" (a dropdown has no typos to forgive)."""
    if scope not in _VALID_SCOPES:
        raise HTTPException(
            status_code=400,
            detail=f"scope must be one of {sorted(_VALID_SCOPES)}, got {scope!r}",
        )
    return scope


@router.post("/{agent_id}/approvals/{approval_id}/approve")
def approve(agent_id: str, approval_id: int, scope: str = Body(_SCOPE_ONCE, embed=True)) -> dict:
    """Run the approved action for REAL — same path as `mpm agent approve` / the htmx UI.

    `scope` (v88 P3): "once" (default) decides just this row; "always"/"deny" ALSO
    teaches a standing rule via `gw.approval_rules.add_rule` — the exact two-step the
    chat path's `_decide()` runs (approve/reject, then learn), so a web decision with
    scope creates the identical rule row a chat decision would.
    """
    scope = _validate_scope(scope)
    loaded = require_agent(agent_id)
    gw = build_gateway(loaded)
    pending = next((p for p in gw.pending_approvals() if p.id == approval_id), None)
    try:
        # Agent-bound dispatch (v31 P2): native types (schedule_update) get their identity
        # closure from THIS route's agent_id; mcp/email fall through to the shared dispatch.
        from my_crew.actions.approved_dispatch import make_agent_bound_dispatch

        gw.approve(approval_id, handler=make_agent_bound_dispatch(agent_id, loaded.config))
    except ValueError as exc:  # unknown / already-consumed id
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except HardBlockedError as exc:  # Lớp A — never approvable
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except RuntimeError as exc:  # post failed — gateway reverts to pending; retryable
        raise HTTPException(
            status_code=502, detail=f"post failed (still pending, retry): {exc}"
        ) from None
    else:
        if scope != _SCOPE_ONCE and pending is not None:
            gw.approval_rules.add_rule(
                pending.action, scope=scope, created_by=f"{agent_id} via web",
            )
    finally:
        gw.close()
    return {"agent_id": agent_id, "approved": approval_id, "pending": _pending_json(loaded)}


@router.post("/{agent_id}/approvals/{approval_id}/reject")
def reject(agent_id: str, approval_id: int, scope: str = Body(_SCOPE_ONCE, embed=True)) -> dict:
    """Reject (audit, no post). Same `scope` contract as `approve` — "deny" teaches a
    standing block rule from the rejected action."""
    scope = _validate_scope(scope)
    loaded = require_agent(agent_id)
    gw = build_gateway(loaded)
    pending = next((p for p in gw.pending_approvals() if p.id == approval_id), None)
    try:
        # False = unknown id, or another surface decided this row first. Same 400 the
        # approve path gives for an already-consumed id: the banner must refresh rather
        # than show a rejection that never happened.
        if not gw.reject(approval_id):
            raise HTTPException(
                status_code=400,
                detail=f"Approval id={approval_id} is unknown or no longer pending.",
            )
        if scope != _SCOPE_ONCE and pending is not None:
            gw.approval_rules.add_rule(
                pending.action, scope=scope, created_by=f"{agent_id} via web",
            )
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
