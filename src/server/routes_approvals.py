"""Lớp B approve/reject on the dashboard (v2 M2-P7 Slice 2).

HTML-partial / htmx-native: each route returns an HTML fragment that swaps in, never
JSON. Approve is a TWO-STEP flow — list → confirm partial (shows what will be posted)
→ confirm POST — so the operator sees exactly what goes live before the real Slack
post. Reject is one-click.

Approve does the SAME real-post path as the CLI: build the per-agent gateway, call
`gw.approve(id, handler=dispatch_approved_action)`. Lớp A hard-deny + audit + dedup
still apply. The gateway is built per request and CLOSED in a finally (no fd leak in
the long-lived server). The pending action is already redacted at enqueue, so rendering
it is safe.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.actions.action_gateway import HardBlockedError
from src.actions.approved_dispatch import dispatch_approved_action
from src.server import agent_views
from src.server.routes_dashboard import templates

router = APIRouter(tags=["approvals"])


def _require_agent(agent_id: str):
    """Load a REGISTERED agent's profile at its own data dir, or 404.

    The registry-membership check also covers path-escape: a malformed id is never
    registered, so it never reaches a data-dir build.
    """
    from src.profile.loader import load_profile
    from src.runtime.agent_paths import agent_data_dir

    if agent_id not in {e.id for e in agent_views.load_registry()}:
        raise HTTPException(status_code=404, detail=f"unknown agent {agent_id!r}")
    return load_profile(agent_id, data_dir=agent_data_dir(agent_id))


def _gateway(loaded):
    from src.actions.action_gateway import ActionGateway

    return ActionGateway(
        loaded.settings, external_channels=loaded.config.slack_external_channels
    )


def _list_partial(request: Request, agent_id: str, loaded):
    gw = _gateway(loaded)
    try:
        pending = gw.pending_approvals()
    finally:
        gw.close()
    return templates.TemplateResponse(
        request, "approvals/list.html",
        {"agent_id": agent_id, "pending": pending},
    )


@router.get("/dashboard/agents/{agent_id}/approvals")
def approvals_list(agent_id: str, request: Request):
    """The pending-approvals partial (rows with action detail + approve/reject buttons)."""
    return _list_partial(request, agent_id, _require_agent(agent_id))


@router.get("/dashboard/agents/{agent_id}/approvals/{approval_id}/confirm")
def approve_confirm(agent_id: str, approval_id: int, request: Request):
    """Confirm partial: shows WHAT will be posted before the real approve POST."""
    loaded = _require_agent(agent_id)
    gw = _gateway(loaded)
    try:
        match = next((p for p in gw.pending_approvals() if p.id == approval_id), None)
    finally:
        gw.close()
    if match is None:
        raise HTTPException(status_code=404, detail=f"no pending approval {approval_id}")
    return templates.TemplateResponse(
        request, "approvals/confirm.html",
        {"agent_id": agent_id, "p": match},
    )


@router.post("/dashboard/agents/{agent_id}/approvals/{approval_id}/approve")
def approve(agent_id: str, approval_id: int, request: Request):
    """Run the approved action for REAL (same path as `mpm agent approve`)."""
    loaded = _require_agent(agent_id)
    gw = _gateway(loaded)
    try:
        gw.approve(approval_id, handler=lambda a: dispatch_approved_action(a, loaded.config))
    except ValueError as exc:  # unknown / already-consumed id
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except HardBlockedError as exc:  # Lớp A — never approvable
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except RuntimeError as exc:  # handler/post failure — gateway reverts to pending; retryable
        raise HTTPException(
            status_code=502, detail=f"post failed (still pending, retry): {exc}"
        ) from None
    finally:
        gw.close()
    return _list_partial(request, agent_id, loaded)  # refreshed list


@router.post("/dashboard/agents/{agent_id}/approvals/{approval_id}/reject")
def reject(agent_id: str, approval_id: int, request: Request):
    """Reject (audit, no post). One-click."""
    loaded = _require_agent(agent_id)
    gw = _gateway(loaded)
    try:
        gw.reject(approval_id)
    finally:
        gw.close()
    return _list_partial(request, agent_id, loaded)
