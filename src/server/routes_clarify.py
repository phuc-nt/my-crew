"""Clarify routes (v33 P4) — the web half of the CEO Q&A surface.

GET lists pending questions (rendered in Duyệt); POST answers one. The answer goes
through the same first-answer-wins service the Telegram button path uses, so a web
click and a Telegram tap can never both land. Auth-protected (/api, not public).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/clarify", tags=["clarify"])


@router.get("/pending")
def list_pending() -> dict:
    from src.runtime.clarify_store import ClarifyStore
    from src.runtime.team_task_paths import clarify_db_path

    store = ClarifyStore(clarify_db_path())
    try:
        rows = store.list_pending()
    finally:
        store.close()
    return {"questions": [
        {
            "id": r.id, "agent_id": r.agent_id, "task_id": r.task_id,
            "question": r.question, "options": list(r.options),
            "asked_at": r.asked_at, "expires_at": r.expires_at,
        }
        for r in rows
    ]}


@router.post("/{clarify_id}/answer")
def answer(clarify_id: int, answer: str = Body(..., embed=True)) -> dict:
    from src.runtime.clarify_service import apply_answer

    if not str(answer).strip():
        raise HTTPException(status_code=400, detail="Câu trả lời trống.")
    landed = apply_answer(clarify_id, str(answer))
    if not landed:
        raise HTTPException(
            status_code=409,
            detail="Câu hỏi này đã được trả lời hoặc đã hết hạn.",
        )
    return {"ok": True, "id": clarify_id}
