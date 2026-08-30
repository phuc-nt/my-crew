"""`mpm crew assign|status|overview` (phase 2, plan `260830-1311-zalo-business-fleet`).

Same control-plane surface `/api/control-plane/*` exposes over HTTP, but IN-PROCESS —
a script/cron job running on the same host does not need to spin up the web server or
hold a session cookie. Both entry points call the exact same functions
(`ops_assign_team_task.preview_assign_team_task` / `run_assign_team_task`,
`control_plane_views.build_task_status` / `build_overview`), so the two surfaces can
never drift apart in behavior — only in transport.

    mpm crew assign "<brief>" [--room <room_id>] [--yes]
    mpm crew status <task_id>
    mpm crew overview
"""

from __future__ import annotations

import sys

from my_crew.entrypoints.mpm import _flag_value

#: Flags in `mpm crew assign` that consume the NEXT argv token as their value. Any
#: flag not in this set is treated as a boolean switch (its token is dropped, nothing
#: after it is consumed) when computing the free-text positional args below.
_VALUE_FLAGS = ("--room",)


def _positional_args(args: list[str]) -> list[str]:
    """Argv tokens that are neither a flag nor a value flag's argument.

    A naive `[a for a in args if not a.startswith("--")]` (the pre-fix logic) drops
    the FLAG token but not the VALUE right after it — so `--room X "brief"` left `X`
    in the positional list and `brief` got silently discarded (`positional[0]` picked
    up the room id as the brief, and the real brief vanished with no error). This
    walks the list once, skipping a value-flag's argument together with the flag.
    """
    out: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token in _VALUE_FLAGS:
            i += 2  # skip the flag AND its value
            continue
        if token.startswith("--"):
            i += 1  # boolean flag: skip just the flag
            continue
        out.append(token)
        i += 1
    return out


def run_crew_control_plane(sub: str, args: list[str]) -> int:
    """Dispatch one control-plane CLI subcommand. Returns a process exit code."""
    if sub == "assign":
        return _assign(args)
    if sub == "status":
        return _status(args)
    if sub == "overview":
        return _overview(args)
    print(
        f"error: unknown crew subcommand {sub!r}. Dùng: assign|status|overview|init",
        file=sys.stderr,
    )
    return 2


def _assign(args: list[str]) -> int:
    """`mpm crew assign "<brief>" [--room <room_id>] [--yes]` — mints a new preview
    (1-step confirm with `--yes`), OR `mpm crew assign --confirm <task_id> <plan_hash>`
    — step 2 of the default 2-step flow, confirming an EXACT prior preview."""
    if "--confirm" in args:
        positional = _positional_args(args)
        if len(positional) < 2:
            print("usage: mpm crew assign --confirm <task_id> <plan_hash>", file=sys.stderr)
            return 2
        return _confirm_assign(positional[0], positional[1])

    positional = _positional_args(args)
    if not positional:
        print('usage: mpm crew assign "<mô tả việc>" [--room <room_id>] [--yes]',
              file=sys.stderr)
        return 2
    brief = positional[0]
    room_id = _flag_value(args, "--room")
    confirm = "--yes" in args

    from my_crew.agent.ops_assign_team_task import preview_assign_team_task

    slots: dict[str, str] = {"brief": brief}
    if room_id:
        slots["room_id"] = room_id
    try:
        preview_text = preview_assign_team_task(slots)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(preview_text)
    task_id = slots.get("task_id", "")
    plan_hash = slots.get("plan_hash", "")
    if slots.get("auto_confirmed"):
        return 0  # company-wide autopilot already confirmed inside preview
    if not confirm:
        print(f"\nĐể xác nhận: mpm crew assign --confirm {task_id} {plan_hash}")
        return 0
    return _confirm_assign(task_id, plan_hash)


def _confirm_assign(task_id: str, plan_hash: str) -> int:
    from my_crew.agent.ops_assign_team_task import run_assign_team_task

    try:
        run_text = run_assign_team_task({"task_id": task_id, "plan_hash": plan_hash})
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(run_text)
    return 0


def _status(args: list[str]) -> int:
    """`mpm crew status <task_id>` — unified state/steps/cost/delivery/route."""
    if not args:
        print("usage: mpm crew status <task_id>", file=sys.stderr)
        return 2
    task_id = args[0]

    from my_crew.server.control_plane_views import build_task_status

    status = build_task_status(task_id)
    if status is None:
        print(f"error: không tìm thấy việc `{task_id}`", file=sys.stderr)
        return 1

    state = status["state"]
    print(f"[{status['task_id']}] {status['title']}")
    print(f"  trạng thái: {state['status']}  |  PIC: {state['pic_id']}")
    for step in status["steps"]:
        print(f"  - {step['step_id']} ({step['status']}): {step['title']}"
              f" → {step['assigned_to']}")
    cost = status["cost"]
    print(f"  chi phí: ${cost['total_cost_usd']:.4f}")
    delivery = status["delivery"]
    print(f"  giao hàng: {delivery['status']} (lần thử: {delivery['attempts']})")
    return 0


def _overview(args: list[str]) -> int:  # noqa: ARG001 — no flags yet, kept for symmetry
    """`mpm crew overview` — 4-block fleet snapshot (registry/health/queue/approvals)."""
    from my_crew.server.control_plane_views import build_overview

    overview = build_overview()
    registry = overview["registry"]
    print(f"Đội ngũ: {len(registry['agents'])} agent")
    for agent in registry["agents"]:
        flag = "bật" if agent["enabled"] else "tắt"
        print(f"  - {agent['agent_id']} ({flag}): {agent.get('name', '')}")

    health = overview["health"]
    coord = "OK" if health["coordinator_ok"] else "LỖI"
    print(f"Coordinator: {coord}")
    for integ in health["integrations"]:
        mark = "OK" if integ["ok"] else "LỖI"
        print(f"  - {integ['label']}: {mark}")

    queue = overview["queue"]
    print(f"Hàng đợi: {queue['depth']} đang mở, {queue['running']} đang chạy, "
          f"{queue['stalled']} bị kẹt")

    approvals = overview["approvals"]
    print(f"Chờ duyệt: {approvals['pending_total']} tổng")
    for agent_id, count in approvals["pending_by_agent"].items():
        print(f"  - {agent_id}: {count}")
    return 0
