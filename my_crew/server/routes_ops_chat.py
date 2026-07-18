"""CEO chat-ops web endpoint (v6 M14b) — the web face of the ops dialogue.

The dashboard's Chat box POSTs a message here; this drives the SAME `handle_ops_message`
engine the Telegram DM path uses (M14a), against the SAME per-operator conversation store
under the admin agent's data dir. So a dialogue started in the browser and continued on
Telegram (or vice-versa) shares one draft — the conversation_key is the admin agent's
configured `ops_operator_id`, not the transport.

Posture: localhost, no-auth (unchanged until M16). There is no per-request operator
identity on the web (a browser has none), so the web IS the operator by construction —
the same trust level as the existing no-auth admin write routes (create/enable/delete).
When M16 adds auth, this route sits behind it like every other.

Only an admin-domain agent with an `ops_operator_id` configured can be chatted with; any
other agent returns 400 (nothing to administer through).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from my_crew.runtime.agent_state_reader import read_all_agent_states

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ops", tags=["ops-chat"])


def _find_ops_agent():
    """Return (admin_agent_id, operator_id, loaded_profile) for the admin ops chat agent.

    The design is SINGLE admin ops agent: web keys the conversation store off this agent's
    data_dir, and the Telegram side (`qa_answer._is_ops_operator`) matches by operator id —
    if two admin agents shared an operator id, a draft started on web (stored under the
    first agent) would not be found by a Telegram mention landing on the second agent's
    worker (drafts diverge). So we pick the first-in-registry admin ops agent
    DETERMINISTICALLY and log a loud warning if more than one exists, surfacing the
    misconfiguration instead of letting cross-surface drafts silently split.

    Raises HTTPException(400) when no admin agent has an ops operator configured — the
    Chat box shows that message instead of failing mid-conversation.
    """
    from my_crew.server.ops_helpers import require_agent

    matches: list[tuple[str, str, object]] = []
    for state in read_all_agent_states():
        agent_id = state.get("agent_id")
        if not agent_id:
            continue
        try:
            loaded = require_agent(agent_id)
        except HTTPException:
            continue
        telegram = getattr(loaded.config, "telegram", None)
        operator = getattr(telegram, "ops_operator_id", "") if telegram else ""
        if getattr(loaded, "domain", "") == "admin" and operator:
            matches.append((agent_id, operator, loaded))
    if not matches:
        raise HTTPException(
            status_code=400,
            detail="Chưa có agent quản trị (domain 'admin' + telegram.ops_operator_id) để chat. "
                   "Tạo/ cấu hình một agent admin trước.",
        )
    if len(matches) > 1:
        logger.warning(
            "multiple admin ops agents configured (%s) — web chat uses %r; a draft started "
            "here may not be found by a Telegram mention on another admin agent. Wire ops "
            "chat to a SINGLE admin agent.",
            [m[0] for m in matches], matches[0][0],
        )
    return matches[0]


@router.get("/chat/available")
def ops_chat_available() -> dict:
    """Whether the Chat box can be used (an admin ops agent exists). Never raises."""
    try:
        agent_id, _operator, _loaded = _find_ops_agent()
        return {"available": True, "agent_id": agent_id}
    except HTTPException as exc:
        return {"available": False, "reason": exc.detail}


@router.get("/chat/commands")
def ops_chat_commands() -> dict:
    """The ops catalog as a discoverable list (v32 audit: chat-only capabilities were
    invisible until a command FAILED to match). Ids + descriptions only — never slots'
    internals or handlers."""
    from my_crew.agent.ops_catalog import OPS_COMMANDS

    return {
        "commands": [
            {"id": cid, "description": spec.get("description", ""),
             "readonly": bool(spec.get("readonly"))}
            for cid, spec in OPS_COMMANDS.items()
        ]
    }


@router.post("/chat")
def ops_chat(message: str = Body(..., embed=True)) -> dict:
    """One ops dialogue turn from the web. Returns {reply}.

    Drives the shared engine + shared per-operator store, so this is byte-for-byte the
    same conversation as the Telegram path. An empty engine reply (the CEO asked a plain
    question, not an ops command) is surfaced as a gentle hint rather than an empty bubble
    — the web Chat box has no Q&A grounding fallback (that lives on the Telegram inbox).
    """
    text = str(message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="message trống")

    from my_crew.agent.ops_chat import handle_ops_message
    from my_crew.agent.ops_conversation_store import OpsConversationStore
    from my_crew.llm.client import LlmClient

    agent_id, operator, loaded = _find_ops_agent()
    store = OpsConversationStore(Path(loaded.settings.data_dir) / "ops_conversation.sqlite3")
    try:
        reply, _cost = handle_ops_message(
            message=text, conversation_key=operator, store=store,
            llm=LlmClient(loaded.settings), now=time.time(),
        )
    finally:
        store.close()
    if not reply:
        reply = ("Mình quản lý đội qua các lệnh: tạo agent, bật/tắt agent, xem trạng thái, "
                 "xem chi phí. Bạn thử nói một trong số đó nhé.")
    return {"reply": reply, "agent_id": agent_id}
