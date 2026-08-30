"""Control-plane API (phase 2, plan `260830-1311-zalo-business-fleet`) — a stable
HTTP contract for a caller OUTSIDE the SPA (script, CLI, another agent): one door
for "giao việc / xem trạng thái / xem toàn cảnh đội".

Design decision D2 (brainstorm report): NO db merge — this router is a thin layer
that wraps the SAME functions the SPA composer uses (`ops_assign_team_task
.preview_assign_team_task` / `run_assign_team_task`) and the SAME read-only views
`control_plane_views` builds from existing stores. The hash-bind (preview persists
a plan + content hash; confirm only flips that EXACT hash — TOCTOU-proof) lives
entirely in `ops_assign_team_task` and is NOT reimplemented here.

Two delegate modes:
  - 2-step (default): POST returns a preview + `task_id`/`plan_hash`; the caller
    calls POST again with `confirm: true` and both to actually dispatch — mirrors
    the SPA's preview/confirm buttons.
  - 1-step (`confirm: true` on the FIRST call, with `task_id` absent): preview then
    immediately confirm the just-minted hash server-side — same code path
    `preview_assign_team_task`'s own company-wide autopilot flag uses, just
    triggered per-request instead of by a global flag.

Audit: every delegate call (2-step confirm OR 1-step) appends one row to the
SHARED team-tasks audit trail (`team_tasks_root()/audit/audit.jsonl` — the same
hash-chained file `mpm agent audit --team verify` checks) tagged
`actor="control_plane_api"`, so a caller outside the SPA is distinguishable in the
trail from `ceo-chat`/the office composer. Best-effort: an audit-append failure
must never block the underlying assign/confirm, which has already committed.

Auth: NOT in `auth._PUBLIC_PREFIXES` — protected exactly like every other `/api`
route (AuthMiddleware gates it when web auth is enabled, no different from the SPA).

Read-only everywhere except `/delegate`; no route here opens a SQLite file
directly — every read goes through `control_plane_views` (which itself only calls
existing store APIs).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/control-plane", tags=["control-plane"])

#: Same body-size ceiling `routes_office_assign.post_preview` uses — a pasted
#: document must not inflate the decompose prompt unbounded.
_MAX_BRIEF_CHARS = 4000


def _audit_delegate(*, task_id: str, mode: str, ok: bool, detail: str) -> None:
    """Append one row to the shared team-tasks audit trail, tagged as this API's
    own source. Best-effort — swallows its own failure (same posture as
    `office_room_append.append_office_event`: an observability write must never
    undo or block a decision that already committed)."""
    try:
        from my_crew.audit.audit_log import AuditEntry, AuditLog
        from my_crew.runtime.team_task_paths import team_tasks_root

        AuditLog(team_tasks_root() / "audit" / "audit.jsonl").record(AuditEntry(
            action_type="control_plane_delegate",
            tool=f"control_plane:delegate:{mode}",
            verdict="allow" if ok else "deny",
            reason=detail,
            params={"task_id": task_id},
            actor="control_plane_api",
        ))
    except Exception:  # noqa: BLE001 — audit is observability, never the source of truth
        logger.warning("control-plane delegate: audit append failed", exc_info=True)


@router.post("/delegate")
def post_delegate(
    brief: str = Body("", embed=True),
    task_id: str = Body("", embed=True),
    plan_hash: str = Body("", embed=True),
    confirm: bool = Body(False, embed=True),
    room_id: str = Body("", embed=True),
) -> dict:
    """Delegate work — 2-step hash-bind by default, 1-step when `confirm: true`.

    Call shapes:
      1. `{"brief": "..."}` → preview only; returns `task_id`/`plan_hash` to echo
         back for step 2 (or `auto_confirmed: true` if the COMPANY-wide autopilot
         flag already ran the confirm inside the preview — unrelated to this
         route's own `confirm` param).
      2. `{"task_id": ..., "plan_hash": ..., "confirm": true}` → confirms the
         EXACT previewed plan (TOCTOU-proof; a stale hash is a clean 409).
      3. `{"brief": "...", "confirm": true}` → one-step: preview THEN immediately
         confirm the just-minted hash, in the same request.
    """
    if task_id:
        return _delegate_confirm_only(task_id, plan_hash)
    if not isinstance(brief, str) or not brief.strip():
        raise HTTPException(status_code=400, detail="cần mô tả việc cần giao (brief)")
    if len(brief) > _MAX_BRIEF_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"mô tả việc quá dài (tối đa {_MAX_BRIEF_CHARS} ký tự)",
        )
    return _delegate_from_brief(brief, room_id=room_id, confirm=confirm)


def _delegate_confirm_only(task_id: str, plan_hash: str) -> dict:
    """Step 2 of the 2-step flow: confirm a plan a PRIOR call already previewed."""
    if not plan_hash:
        raise HTTPException(status_code=400, detail="cần plan_hash để xác nhận")
    from my_crew.agent.ops_assign_team_task import run_assign_team_task

    try:
        text = run_assign_team_task({"task_id": task_id, "plan_hash": plan_hash})
    except ValueError as exc:
        _audit_delegate(task_id=task_id, mode="confirm", ok=False, detail=str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from None
    _audit_delegate(task_id=task_id, mode="confirm", ok=True, detail=text)
    return {"v": 1, "task_id": task_id, "confirmed": True, "text": text}


def _delegate_from_brief(brief: str, *, room_id: str, confirm: bool) -> dict:
    """Step 1 (2-step) or the whole flow (1-step opt-in `confirm=True`)."""
    from my_crew.agent.ops_assign_team_task import preview_assign_team_task

    slots: dict[str, str] = {"brief": brief.strip()}
    if isinstance(room_id, str) and room_id.strip():
        slots["room_id"] = room_id.strip()
    try:
        preview_text = preview_assign_team_task(slots)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    minted_task_id = slots.get("task_id", "")
    minted_plan_hash = slots.get("plan_hash", "")
    # `preview_assign_team_task` may ALREADY have auto-confirmed (company-wide
    # autopilot flag) — in that case there is nothing left for this route to do.
    already_confirmed = bool(slots.get("auto_confirmed"))

    if not confirm or already_confirmed:
        return {
            "v": 1,
            "task_id": minted_task_id,
            "plan_hash": minted_plan_hash,
            "preview_text": preview_text,
            "confirmed": already_confirmed,
            "route_mode": slots.get("route_mode", ""),
        }

    # 1-step opt-in: confirm the plan THIS call just minted, same hash-bind path.
    from my_crew.agent.ops_assign_team_task import run_assign_team_task

    try:
        run_text = run_assign_team_task(
            {"task_id": minted_task_id, "plan_hash": minted_plan_hash}
        )
    except ValueError as exc:
        _audit_delegate(task_id=minted_task_id, mode="one_step", ok=False, detail=str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from None
    _audit_delegate(task_id=minted_task_id, mode="one_step", ok=True, detail=run_text)
    return {
        "v": 1,
        "task_id": minted_task_id,
        "plan_hash": minted_plan_hash,
        "preview_text": preview_text,
        "confirmed": True,
        "text": run_text,
        "route_mode": slots.get("route_mode", ""),
    }


@router.get("/tasks/{task_id}")
def get_task_status(task_id: str) -> dict:
    """Unified status for one team task — state, steps, cost, delivery, route."""
    from my_crew.server.control_plane_views import build_task_status

    status = build_task_status(task_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"không tìm thấy việc `{task_id}`")
    return status


@router.get("/overview")
def get_overview() -> dict:
    """4-block fleet overview: registry / health / queue / approvals.

    Each block fail-degrades independently in `control_plane_views.build_overview`
    — this route never adds its own try/except around it (the degrade discipline
    lives at the view layer, one place).
    """
    from my_crew.server.control_plane_views import build_overview

    return build_overview()
