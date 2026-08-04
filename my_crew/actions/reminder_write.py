"""reminder_create / reminder_cancel WRITE — one-shot timed reminders (v65).

The secretary's chat commands ("3h nhắc anh gọi X") funnel here through the Action
Gateway: Lớp A scans the payload (`hard_block._hard_deny_reminder` — secrets, text
bounds, RFC3339 shape), Lớp B queues in guarded mode / runs audited in autonomous.

Agent-bound like `schedule_update`/`team_task_*`: the store written is ALWAYS the
acting agent's own (`actor_id` is a closure over the call site's `loaded.profile_id`,
never a payload field), so one agent can never plant or cancel reminders in another's
store. Cancel additionally verifies the row exists and is still pending — cancelling
an already-sent reminder reports honestly instead of pretending.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Handler = Callable[[dict[str, Any]], str]


def make_reminder_handler(actor_id: str) -> Handler:
    """Build the gateway handler bound to ONE acting agent's identity/store."""

    def _handler(action: dict[str, Any]) -> str:
        atype = str(action.get("type", "")).lower()
        if atype == "reminder_create":
            return _create(actor_id, action)
        if atype == "reminder_cancel":
            return _cancel(actor_id, action)
        raise PermissionError(f"reminder handler refuses action type {atype!r}")

    return _handler


def _open_store(actor_id: str):
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.reminder_store import ReminderStore, reminders_db_path

    return ReminderStore(reminders_db_path(agent_data_dir(actor_id)))


def _create(actor_id: str, action: dict[str, Any]) -> str:
    chat_id = str(action.get("chat_id") or "").strip()
    text = str(action.get("text") or "").strip()
    due_at = str(action.get("due_at") or "").strip()
    if not chat_id or not text or not due_at:
        raise PermissionError("reminder_create refused: chat_id, text and due_at are required")
    store = _open_store(actor_id)
    try:
        reminder_id = store.add(chat_id=chat_id, text=text, due_at=due_at)
    finally:
        store.close()
    return f"đã đặt nhắc #{reminder_id} lúc {due_at}: {text[:80]}"


def _cancel(actor_id: str, action: dict[str, Any]) -> str:
    raw_id = action.get("reminder_id")
    try:
        reminder_id = int(raw_id)
    except (TypeError, ValueError):
        raise PermissionError("reminder_cancel refused: reminder_id must be an integer") from None
    store = _open_store(actor_id)
    try:
        cancelled = store.cancel(reminder_id)
    finally:
        store.close()
    if not cancelled:
        raise PermissionError(
            f"reminder_cancel refused: nhắc #{reminder_id} không tồn tại hoặc đã gửi/đã huỷ"
        )
    return f"đã huỷ nhắc #{reminder_id}"
