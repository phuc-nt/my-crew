"""office-pack chat-command catalog (v31 P3).

Kanban card actions for office staff: propose a work card for a colleague and move a
card's status. Both are NATIVE gateway types (no MCP server) — validated at pack load
against the vetted-type set (registry._load_commands), structurally hard-checked by
`hard_block._hard_deny_team_task` at runtime, and permission-checked against the
team-task STORE by `team_task_write.make_team_task_handler` with the ACTING agent's
identity closed over at the call site (an args field cannot forge the actor).
"""

from __future__ import annotations

from typing import Any


def _create_task_args(args: dict[str, str], config: Any) -> dict[str, Any]:
    """Payload for `team_task_create`. Carries no actor id — the creator is always the
    agent answering the chat (handler closure). The dedup hint is state-bearing (H3):
    title + assignee + minute stamp, so re-proposing the same card later is a new key.
    """
    from datetime import datetime

    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M")
    out: dict[str, Any] = {
        "title": args["title"],
        "assignee": args["assignee"],
        "dedup_hint": f"create:{args['assignee']}:{args['title'][:80]}:{stamp}",
    }
    if args.get("detail"):
        out["detail"] = args["detail"]
    return out


def _move_task_args(args: dict[str, str], config: Any) -> dict[str, Any]:
    """Payload for `team_task_move`. State-bearing dedup hint: target status + minute
    stamp, so move→reopen→move again is three keys, never swallowed as a duplicate."""
    from datetime import datetime

    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M")
    return {
        "task_id": args["task_id"],
        "status": args["status"],
        "dedup_hint": f"move:{args['task_id']}:{args['status']}:{stamp}",
    }


COMMANDS: dict[str, dict] = {
    "create_team_task": {
        "description": (
            "Đề xuất một thẻ việc đội mới, giao cho một đồng nghiệp. args: title (tiêu "
            "đề việc), assignee (mã agent nhận việc, vd 'noi-dung'), detail (tuỳ chọn, "
            "mô tả thêm). Thẻ ở trạng thái chờ kế hoạch — chưa tự chạy."
        ),
        "type": "team_task_create",
        "args_schema": {
            "title": {"required": True, "max_len": 200},
            "assignee": {"required": True, "max_len": 40,
                         "pattern": r"[a-z0-9][a-z0-9_-]*"},
            "detail": {"required": False, "max_len": 1000},
        },
        "build_args": _create_task_args,
    },
    "move_team_task": {
        "description": (
            "Chuyển trạng thái một thẻ việc đội mà bạn tham gia (là PIC/người tạo/"
            "người nhận bước). args: task_id (mã việc), status (một trong: planning, "
            "open, running, done, cancelled, stalled)"
        ),
        "type": "team_task_move",
        "args_schema": {
            "task_id": {"required": True, "max_len": 40, "pattern": r"[a-z0-9][a-z0-9-]*"},
            "status": {"required": True, "max_len": 20,
                       "pattern": r"planning|open|running|done|cancelled|stalled"},
        },
        "build_args": _move_task_args,
    },
}
