"""Per-agent Telegram bind for Agent Studio (v7 M18a). Session-auth-gated (runs AFTER setup).

The wizard collects a bot token and this writes it to .env (under a whitelisted
`<AGENT>_TELEGRAM_BOT_TOKEN` name) + adds the `telegram:` block to the agent's profile.yaml.
Because `resolve_bot_token` reads os.environ at CALL time (not once at startup), we
`load_dotenv(override=True)` the just-written key so the next poll/send sees it WITHOUT a
restart — unlike the session secret (M16/M17), a per-call env read needs no bounce.

The token is validated against Telegram (`getMe`) before persisting, so a typo fails loudly
in the wizard instead of silently producing a dead bot.
"""

from __future__ import annotations

import re

import yaml
from fastapi import Body, HTTPException

from my_crew.server import env_writer
from my_crew.server.routes_agent_studio_shared import _AGENT_ID_RE, router


def _token_env_name(agent_id: str) -> str:
    """The .env key holding this agent's bot token: `<AGENT>_TELEGRAM_BOT_TOKEN` (id upper,
    non-alnum → underscore) — matches the whitelist pattern env_writer enforces."""
    slug = re.sub(r"[^A-Z0-9]", "_", agent_id.upper())
    return f"{slug}_TELEGRAM_BOT_TOKEN"


@router.post("/{agent_id}/telegram")
def bind_telegram(
    agent_id: str,
    token: str = Body(..., embed=True),
    chat_ids: list[str] = Body(default=[], embed=True),  # noqa: B008
) -> dict:
    """Validate + persist a Telegram bot for this agent, then make it live without a restart.

    Steps: getMe(token) → write `<AGENT>_TELEGRAM_BOT_TOKEN` to .env (whitelisted) → add the
    `telegram:` block to profile.yaml (validated by save_profile_yaml) → override-load the
    key so the running process sees it.
    """
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=400, detail=f"agent id không hợp lệ: {agent_id!r}")
    token = str(token).strip()
    if not token:
        raise HTTPException(status_code=400, detail="token trống")
    clean_chats = [c for c in chat_ids if str(c).strip()]
    # Require at least one chat id BEFORE any write (review C1). The telegram config builder
    # rejects an empty chat_ids at load, so persisting the token first then failing on the
    # profile would leave a partial write (.env has the token, profile has no block). Failing
    # early keeps the two in sync. The UI collects a chat id (typed or picked from getUpdates)
    # before enabling "Gắn bot".
    if not clean_chats:
        raise HTTPException(
            status_code=400,
            detail="Cần ít nhất một chat id. Nhắn bot một câu rồi bấm 'Lấy chat gần đây', "
                   "hoặc nhập chat id thủ công.",
        )

    # 1. Validate against Telegram — a bad token fails HERE, not silently at first poll.
    from my_crew.actions.telegram_write import api_call

    try:
        me = api_call(token, "getMe")
    except Exception as exc:  # noqa: BLE001 — surface the Bot API error to the wizard
        raise HTTPException(status_code=400, detail=f"token không hợp lệ: {exc}") from None
    bot_username = me.get("username") if isinstance(me, dict) else None

    # 2. Persist the token under the whitelisted per-agent key name.
    env_name = _token_env_name(agent_id)
    try:
        env_writer.merge_env({env_name: token}, allow=frozenset(), allow_telegram_token=True)
    except env_writer.DisallowedEnvKey as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    # 3. Add the telegram block to profile.yaml (validated on save).
    _add_telegram_block(agent_id, env_name, [c for c in chat_ids if str(c).strip()])

    # 4. Make the token live NOW (per-call env read → no restart needed, unlike M17 secret).
    from dotenv import load_dotenv

    from my_crew.config.settings import REPO_ROOT

    load_dotenv(REPO_ROOT / ".env", override=True)
    return {"ok": True, "bot_username": bot_username, "env_name": env_name}


def _add_telegram_block(agent_id: str, env_name: str, chat_ids: list[str]) -> None:
    from my_crew.server import profile_editor

    text = profile_editor.read_profile_files(agent_id).get("profile", "")
    doc = yaml.safe_load(text) or {}
    if not isinstance(doc, dict):
        raise HTTPException(status_code=500, detail="profile.yaml hỏng")
    # Merge onto any existing telegram block so a re-bind (e.g. rotating the token) does NOT
    # wipe chat_ids / poll_minutes the operator set earlier. New chat_ids REPLACE only when
    # provided; an empty chat_ids keeps whatever was there.
    tg = dict(doc.get("telegram") or {})
    tg["bot_token_env"] = env_name
    tg.setdefault("poll_minutes", 2)
    if chat_ids:
        tg["chat_ids"] = chat_ids
    doc["telegram"] = tg
    new_text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    try:
        profile_editor.save_profile_yaml(agent_id, new_text)
    except Exception as exc:  # noqa: BLE001 — validation error → 400
        raise HTTPException(status_code=400, detail=f"lưu profile lỗi: {exc}") from None


@router.post("/{agent_id}/telegram/updates")
def telegram_recent_chats(agent_id: str, token: str = Body(..., embed=True)) -> dict:
    """Poll getUpdates with the token the operator just pasted (NOT yet persisted) to surface
    chat ids that recently messaged the bot — so they can pick a chat id BEFORE binding. This
    breaks the bind-needs-chat / getUpdates-needs-token deadlock (review C1/M2): the token
    lives only in this request, nothing is written. Read-only."""
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=400, detail="agent id không hợp lệ")
    token = str(token).strip()
    if not token:
        raise HTTPException(status_code=400, detail="token trống")

    from my_crew.actions.telegram_write import api_call

    try:
        updates = api_call(token, "getUpdates", {"timeout": 0})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"không lấy được tin: {exc}") from None
    chats: dict[str, str] = {}
    for u in updates if isinstance(updates, list) else []:
        chat = (u.get("message") or {}).get("chat") or {}
        cid = chat.get("id")
        if cid is not None:
            chats[str(cid)] = str(chat.get("username") or chat.get("title")
                                  or chat.get("first_name") or "")
    return {"chats": [{"id": k, "name": v} for k, v in chats.items()]}
