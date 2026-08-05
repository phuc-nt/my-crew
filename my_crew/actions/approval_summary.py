"""One-line Vietnamese summary of a queued Lớp B action (v69).

The CEO decides approve/reject from a Telegram message and from chat — surfaces
with no `<details>` fold to hide a raw JSON payload in, unlike the web banner. So
the summary must carry the ONE identifying detail that makes the decision possible
("gửi email tới ai", "chạy gh pr merge trên repo nào") and nothing else.

Two hard rules, both security posture rather than aesthetics:

- **Identity fields only, never bodies/payloads.** A subject line or message body is
  attacker-influenced free text (an LLM worker composed it, possibly from content it
  read). Rendering it next to a confirm prompt is a social-engineering surface. Only
  addressing/target fields are rendered, and they are truncated.
- **Unknown types degrade to a stub, and a stub forbids rule-learning.** A type this
  module does not know is summarized as `<type> (chi tiết xem web)`. The chat approval
  commands refuse to create an always/deny rule from a stub — an operator cannot
  consent to a standing rule over an action they were never shown.

`SUMMARIZABLE_TYPES` is asserted equal to the gateway's `_MUTATING_TYPES` in the
tests: a new mutating type must arrive here in the same change, not silently fall
back to a stub that quietly disables rule-learning for it.
"""

from __future__ import annotations

from typing import Any

# Longest an identity fragment may render before truncation. Keeps one Telegram
# line readable and caps how much attacker-chosen text can reach the CEO's screen.
_MAX_FRAGMENT = 60


def _clip(text: str, limit: int = _MAX_FRAGMENT) -> str:
    """Single-line, length-capped rendering of an identity fragment.

    Newlines are collapsed so a crafted value cannot fake extra message lines
    (e.g. a fake "đã duyệt" line) inside the notification.
    """
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _recipients(action: dict[str, Any]) -> str:
    to = action.get("to")
    if isinstance(to, (list, tuple)):
        names = [str(x) for x in to if x]
    elif to:
        names = [str(to)]
    else:
        names = []
    if not names:
        return "không rõ người nhận"
    head = ", ".join(names[:2])
    return head if len(names) <= 2 else f"{head} +{len(names) - 2} người"


def _email_send(action: dict[str, Any]) -> str:
    return f"gửi email tới {_clip(_recipients(action))}"


def _telegram_send(action: dict[str, Any]) -> str:
    chat = action.get("chat_id") or "không rõ"
    return f"gửi tin Telegram tới chat {_clip(str(chat), 32)}"


def _mcp_tool(action: dict[str, Any]) -> str:
    tool = action.get("tool") or "không rõ"
    return f"gọi công cụ {_clip(str(tool), 48)}"


def _gh_cli(action: dict[str, Any]) -> str:
    argv = action.get("argv")
    parts = [str(a) for a in argv[:3]] if isinstance(argv, (list, tuple)) else []
    return f"chạy gh {_clip(' '.join(parts), 48)}" if parts else "chạy lệnh gh"


def _schedule_update(action: dict[str, Any]) -> str:
    cron = action.get("cron") or action.get("schedule") or ""
    return f"đổi lịch chạy sang {_clip(str(cron), 32)}" if cron else "đổi lịch chạy"


def _team_task_create(action: dict[str, Any]) -> str:
    title = action.get("title") or action.get("task_id") or ""
    return f"tạo thẻ việc đội {_clip(str(title), 48)}" if title else "tạo thẻ việc đội"


def _team_task_move(action: dict[str, Any]) -> str:
    task = action.get("task_id") or ""
    status = action.get("status") or action.get("to_status") or ""
    if task and status:
        return f"chuyển thẻ {_clip(str(task), 32)} sang {_clip(str(status), 24)}"
    return f"chuyển thẻ việc đội {_clip(str(task), 32)}" if task else "chuyển thẻ việc đội"


def _gws_write(action: dict[str, Any]) -> str:
    target = action.get("target") or action.get("doc_id") or action.get("spreadsheet_id") or ""
    if not target:
        return "ghi Google Sheets/Docs"
    return f"ghi Google Sheets/Docs {_clip(str(target), 48)}"


def _reminder_create(action: dict[str, Any]) -> str:
    when = action.get("due_at") or action.get("when") or ""
    return f"đặt nhắc hẹn lúc {_clip(str(when), 32)}" if when else "đặt nhắc hẹn giờ"


def _reminder_cancel(action: dict[str, Any]) -> str:
    rid = action.get("reminder_id") or ""
    return f"huỷ nhắc hẹn {_clip(str(rid), 32)}" if rid else "huỷ nhắc hẹn giờ"


# type -> renderer. Kept in lockstep with the gateway's `_MUTATING_TYPES` by test.
_RENDERERS = {
    "email_send": _email_send,
    "telegram_send": _telegram_send,
    "mcp_tool": _mcp_tool,
    "gh_cli": _gh_cli,
    "schedule_update": _schedule_update,
    "team_task_create": _team_task_create,
    "team_task_move": _team_task_move,
    "gws_write": _gws_write,
    "reminder_create": _reminder_create,
    "reminder_cancel": _reminder_cancel,
}

SUMMARIZABLE_TYPES = frozenset(_RENDERERS)


def is_stub_summary(action: dict[str, Any]) -> bool:
    """True when this action can only be rendered as the generic stub.

    The chat approval commands consult this before offering always/deny: a
    standing rule over an action the operator was shown only as `<type>` is a
    rule they cannot have meaningfully consented to.
    """
    if not isinstance(action, dict):
        return True
    return str(action.get("type", "")).lower() not in SUMMARIZABLE_TYPES


def summarize_action(action: dict[str, Any]) -> str:
    """One Vietnamese line naming what the action does and to what.

    Never raises: a malformed action still has to render something for the CEO,
    because the alternative is a notification that silently never arrives.
    """
    if not isinstance(action, dict):
        return "hành động không đọc được (chi tiết xem web)"
    atype = str(action.get("type", "")).lower()
    render = _RENDERERS.get(atype)
    if render is None:
        return f"{atype or 'không rõ loại'} (chi tiết xem web)"
    try:
        return render(action)
    except Exception:  # noqa: BLE001 — a summary must never break the notice path
        return f"{atype} (chi tiết xem web)"
