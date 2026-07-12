"""pm-pack chat-command catalog (v5 M12).

The CEILING of what a chat mention may ask a PM agent to do. Every entry is validated
at pack load against this pack's allowlist + Lớp A (registry._load_commands) and, at
request time, args are schema-validated in code and the action is FORCE-queued for
human approval — chat never executes directly.

v1 keeps ONE command (create_issue): enough to prove responsibility level 3; grow the
catalog only when the owner asks (trust ladder is a policy decision, not a default).
"""

from __future__ import annotations

from typing import Any


def _create_issue_args(args: dict[str, str], config: Any) -> dict[str, str]:
    """Validated args + the agent's OWN project key from config — the requester cannot
    point the issue at another project."""
    out = {"projectKey": config.jira_project_key, "summary": args["summary"]}
    if args.get("description"):
        out["description"] = args["description"]
    return out


def _schedule_update_args(args: dict[str, str], config: Any) -> dict[str, Any]:
    """Payload for the native `schedule_update` type (v31 P2). Carries NO agent id —
    the target is always the agent answering the chat (identity is a handler closure).

    The dedup hint is STATE-BEARING (target value + minute stamp): a real A→B→A
    re-schedule mints distinct keys, so the no-TTL dedup store can't swallow the
    third change as a "duplicate" of the first.
    """
    from datetime import datetime

    kind, cron = args["kind"], args["cron"]
    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M")
    return {"schedule": {kind: cron}, "dedup_hint": f"{kind}:{cron}:{stamp}"}


COMMANDS: dict[str, dict] = {
    "create_issue": {
        "description": (
            "Tạo Jira issue mới trong project của agent. "
            "args: summary (bắt buộc, tiêu đề ngắn), description (tuỳ chọn, chi tiết)"
        ),
        "server": "jira",
        "tool": "createIssue",
        "args_schema": {
            "summary": {"required": True, "max_len": 200},
            "description": {"required": False, "max_len": 2000},
        },
        "build_args": _create_issue_args,
    },
    "update_my_schedule": {
        "description": (
            "Đổi lịch chạy một báo cáo của CHÍNH agent này (không đổi được lịch agent "
            "khác). args: kind (mã báo cáo, vd 'daily'), cron (biểu thức cron 5 trường, "
            "vd '0 8 * * *' = 8h sáng mỗi ngày; không nhanh hơn mỗi 5 phút). "
            "Hiệu lực từ lần khởi động lại service kế tiếp."
        ),
        "type": "schedule_update",
        "args_schema": {
            "kind": {"required": True, "max_len": 30, "pattern": r"[a-z0-9][a-z0-9_-]*"},
            "cron": {"required": True, "max_len": 60},
        },
        "build_args": _schedule_update_args,
    },
}
