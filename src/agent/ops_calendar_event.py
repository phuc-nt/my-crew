"""CEO chat-ops `create_calendar_event` command (v39 #3) — CODE, not an LLM write tool.

The CEO asks the coordinator to create a Google Calendar event; the ops engine slot-fills
title / start / end / attendees, the CEO confirms, and THIS code builds a FIXED gws_write
argv (`calendar events insert --json {...}`) from those slots and runs it through the
coordinator's Action Gateway. The LLM only fills slots — never an argv — so a crafted
value can't turn the create into a delete/share (and the gateway's Lớp A markers deny
those anyway). Guarded → queued; autonomous → executed + audited.
"""

from __future__ import annotations

import json


def _sender_profile():
    """Coordinator profile = the identity that owns the calendar write."""
    from src.profile.loader import load_profile
    from src.runtime.agent_paths import agent_data_dir
    from src.runtime.company import load_company

    coordinator_id = load_company().coordinator_id
    if not coordinator_id:
        raise ValueError("chưa đặt điều phối (coordinator) — không có danh tính để tạo sự kiện.")
    try:
        return load_profile(coordinator_id, data_dir=agent_data_dir(coordinator_id))
    except (FileNotFoundError, RuntimeError):
        raise ValueError(f"không tải được hồ sơ điều phối '{coordinator_id}'.") from None


def _build_event_body(slots: dict) -> dict:
    """The Calendar event resource, built from validated slots (never free-form argv).

    `start`/`end` are RFC3339 (e.g. 2026-07-20T09:00:00+07:00). Attendees is an optional
    comma list of emails. A missing end defaults to the start (a point event / all-day-ish);
    the CLI still accepts it.
    """
    title = (slots.get("title") or "").strip()
    start = (slots.get("start") or "").strip()
    end = (slots.get("end") or "").strip() or start
    if not title or not start:
        raise ValueError("cần tối thiểu tiêu đề và thời gian bắt đầu (RFC3339).")
    body: dict = {
        "summary": title[:300],
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    attendees = (slots.get("attendees") or "").strip()
    if attendees:
        emails = [a.strip() for a in attendees.split(",") if a.strip() and "@" in a]
        if emails:
            body["attendees"] = [{"email": e} for e in emails[:20]]
    return body


def run_create_calendar_event(slots: dict) -> str:
    """Confirm-time: create the event through the gateway. Returns a human summary."""
    from src.actions.action_gateway import ActionGateway

    loaded = _sender_profile()
    body = _build_event_body(slots)
    # CODE-fixed argv — the slots only fill the --json body, never the subcommand.
    argv = ["calendar", "events", "insert", "--json", json.dumps(body, ensure_ascii=False)]
    action = {
        "type": "gws_write",
        "argv": argv,
        "dedup_hint": f"calendar:{body['summary']}:{body['start']['dateTime']}",
    }
    gateway = ActionGateway(loaded.settings)
    from src.actions.approved_dispatch import dispatch_approved_action

    result = gateway.execute(
        action, handler=lambda a: dispatch_approved_action(a, loaded.config),
    )
    if result.status == "pending_approval":
        return f"Đã xếp hàng chờ duyệt việc tạo sự kiện “{body['summary']}” (chế độ guarded)."
    if result.status == "executed":
        return f"Đã tạo sự kiện “{body['summary']}” lúc {body['start']['dateTime']}."
    if result.status == "dry_run":
        return f"(DRY_RUN) Sẽ tạo sự kiện “{body['summary']}” — chưa tạo thật (đặt DRY_RUN=false)."
    if result.status == "deduplicated":
        return f"KHÔNG tạo: sự kiện “{body['summary']}” cùng giờ đã tạo (trùng)."
    return f"KHÔNG tạo được sự kiện: {result.summary}"


def preview_create_calendar_event(slots: dict) -> str:
    lines = [
        "Mình sẽ TẠO sự kiện lịch:",
        f"- Tiêu đề: {slots.get('title')}",
        f"- Bắt đầu: {slots.get('start')}",
    ]
    if slots.get("end"):
        lines.append(f"- Kết thúc: {slots.get('end')}")
    if slots.get("attendees"):
        lines.append(f"- Người dự: {slots.get('attendees')}")
    lines.append("\nXác nhận tạo? (trả lời: xác nhận / huỷ)")
    return "\n".join(lines)
