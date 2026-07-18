"""Office-composer assignment routes (v15) — the unified office screen's "giao việc" box.

THIN wrappers over the SAME preview/run/cancel functions the ops-chat
`assign_team_task` command uses (`ops_assign_team_task.py`) — the hash-bind
(preview persists a draft plan + hash; confirm flips ONLY that exact hash), the
escalation-route gate, the @PIC parse and the auto-confirm branch all live THERE,
not here. This module only maps HTTP bodies onto the command's `slots` dict.

Deviation from the brainstorm's "reuse ops-chat" lean (documented in the plan): the
chat state machine (collect → awaiting_confirm draft keyed by conversation) fits a
turn-based chat, not a composer with inline Confirm/Cancel buttons — these routes
carry `task_id`+`plan_hash` explicitly instead of parking a conversation draft.

Auth: the `/api` prefix is NOT in `auth._PUBLIC_PREFIXES`, so AuthMiddleware protects
these exactly like every other admin route — do not add them to the public allowlist.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/office/assign", tags=["office-assign"])


@router.get("/staff")
def get_assignable_staff() -> dict:
    """Roster for the composer's @-autocomplete — assignable ids only (coordinator +
    admin excluded by `assignable_staff`, same rule the decompose validator enforces)."""
    from my_crew.agent.team_task_roster import assignable_staff

    return {"staff": [{"id": a, "domain": d} for a, d in assignable_staff()]}


@router.post("/preview")
def post_preview(
    brief: str = Body(..., embed=True), room_id: str = Body("", embed=True),
) -> dict:
    """Decompose the brief (with optional @PIC prefix) and persist the draft plan.

    Returns the preview text + the `task_id`/`plan_hash` pair the confirm call must
    echo back (hash-bind), plus `auto_confirmed` when the company flag already ran the
    confirm inside the preview (the FE then renders a done-card, no buttons)."""
    if not isinstance(brief, str) or not brief.strip():
        raise HTTPException(status_code=400, detail="cần mô tả việc cần giao")
    # Cost guard: the chat path is naturally bounded by Telegram's 4096-char messages;
    # this route needs its own ceiling so a pasted document can't inflate the decompose
    # prompt unbounded.
    if len(brief) > 4000:
        raise HTTPException(status_code=400, detail="mô tả việc quá dài (tối đa 4000 ký tự)")
    from my_crew.agent.ops_assign_team_task import preview_assign_team_task

    slots: dict[str, str] = {"brief": brief.strip()}
    if isinstance(room_id, str) and room_id.strip():
        # v16: assigning from inside a workroom — the new task joins that room.
        slots["room_id"] = room_id.strip()
    try:
        preview_text = preview_assign_team_task(slots)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {
        "preview_text": preview_text,
        "task_id": slots.get("task_id", ""),
        "plan_hash": slots.get("plan_hash", ""),
        "pic_id": slots.get("pic_id", ""),
        "auto_confirmed": bool(slots.get("auto_confirmed")),
    }


@router.post("/confirm")
def post_confirm(
    task_id: str = Body(..., embed=True), plan_hash: str = Body(..., embed=True),
) -> dict:
    """Confirm the EXACT previewed plan (TOCTOU-proof — `confirm_plan` re-verifies the
    hash; a stale/mutated draft reports cleanly instead of dispatching)."""
    from my_crew.agent.ops_assign_team_task import run_assign_team_task

    try:
        text = run_assign_team_task({"task_id": task_id, "plan_hash": plan_hash})
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"text": text}


@router.post("/cancel")
def post_cancel(task_id: str = Body(..., embed=True)) -> dict:
    """Abandon a previewed draft — terminalizes the `planning` row (same cleanup the
    chat flow's on_cancel hook does), so no orphaned draft ever lingers (F11)."""
    from my_crew.agent.ops_assign_team_task import cancel_assign_team_task

    cancel_assign_team_task({"task_id": task_id})
    return {"ok": True}
