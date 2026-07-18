"""CEO chat-ops `send_message` command (v38 #1) — CODE, not an LLM write tool.

The CEO tells the coordinator "gửi tin nhắn tới …"; the ops engine slot-fills channel /
recipient / text, the CEO confirms, and THIS code calls `send_message` (the facade over
the per-channel writers) through the coordinator's Action Gateway. The LLM only fills
slots — it never holds a write tool (that would breach the read-only-toolset moat). Every
send inherits Lớp A/B + trust_mode + audit + dedup from the gateway.
"""

from __future__ import annotations

from my_crew.actions.send_message import SUPPORTED_CHANNELS, SendMessageError, send_message


def _sender_profile():
    """Load the coordinator's profile (identity that owns the send). Raises ValueError with
    a clean chat message when no coordinator is configured."""
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.company import load_company

    coordinator_id = load_company().coordinator_id
    if not coordinator_id:
        raise ValueError("chưa đặt điều phối (coordinator) — không có danh tính để gửi.")
    try:
        return load_profile(coordinator_id, data_dir=agent_data_dir(coordinator_id))
    except (FileNotFoundError, RuntimeError):
        raise ValueError(f"không tải được hồ sơ điều phối '{coordinator_id}'.") from None


def run_send_message(slots: dict[str, str]) -> str:
    """Confirm-time: send the message through the gateway. Returns a human summary."""
    from datetime import datetime

    from my_crew.actions.action_gateway import ActionGateway

    loaded = _sender_profile()
    channel = (slots.get("channel") or "").strip().lower()
    to = (slots.get("to") or "").strip()
    text = slots.get("text") or ""
    # Local day → the writers key dedup off it (one identical send per day+recipient).
    report_date = datetime.now().astimezone().date().isoformat()  # noqa: DTZ005 — local, matches ops clock

    gateway = ActionGateway(
        loaded.settings, external_channels=loaded.config.slack_external_channels,
        actor=getattr(loaded, "profile_id", ""),  # v46
    )
    try:
        result = send_message(
            channel=channel, to=to, text=text,
            gateway=gateway, config=loaded.config, report_date=report_date,
            subject=slots.get("subject") or "",
        )
    except SendMessageError as exc:
        raise ValueError(str(exc)) from None

    # Report the ACTUAL gateway outcome honestly — only "executed" is a real send.
    # dedup/skip/dry-run must not read as "sent" (a CEO resending a corrected message the
    # same day would otherwise be told it went out when dedup silently dropped it).
    if result.status == "pending_approval":
        return f"Đã xếp hàng chờ duyệt việc gửi qua {channel} tới '{to}' (chế độ guarded)."
    if result.status == "executed":
        return f"Đã gửi qua {channel} tới '{to}'."
    if result.status == "dry_run":
        return (f"(DRY_RUN) Sẽ gửi qua {channel} tới '{to}' — chưa gửi thật "
                f"(đặt DRY_RUN=false để gửi).")
    if result.status == "deduplicated":
        return (f"KHÔNG gửi qua {channel} tới '{to}': trùng một tin đã gửi hôm nay "
                f"(đổi nội dung/người nhận nếu cần gửi lại).")
    # skipped (no handler / hard-denied-not-queued) or any other non-send status.
    return f"KHÔNG gửi được qua {channel} tới '{to}': {result.summary}"


def preview_send_message(slots: dict[str, str]) -> str:
    channel = (slots.get("channel") or "").strip().lower()
    if channel not in SUPPORTED_CHANNELS:
        # Surface the constraint early in the confirm text; run() re-validates + raises.
        channel = f"{channel} (⚠️ chỉ hỗ trợ: {', '.join(SUPPORTED_CHANNELS)})"
    text = slots.get("text") or ""
    preview_text = text if len(text) <= 200 else text[:199] + "…"
    return (
        f"Mình sẽ GỬI tin nhắn:\n"
        f"- Kênh: {channel}\n"
        f"- Tới: {slots.get('to')}\n"
        f"- Nội dung: {preview_text}\n\n"
        "Xác nhận gửi? (trả lời: xác nhận / huỷ)"
    )
