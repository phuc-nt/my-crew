"""personal-pack chat-command catalog (v57 3b) — hành động ghi đầu tiên của thư ký.

Một lệnh: tạo sự kiện Google Calendar cho chủ nhân. Native type `gws_write` (vetted tại
pack load), argv CODE-fixed nằm trong `_GWS_ALLOWLIST_PREFIXES` (calendar events insert) —
LLM chỉ điền slot title/start/end/attendees, không bao giờ chạm argv; verb delete/share
bị Lớp A marker chặn trước cả allowlist. Body sự kiện tái dùng builder của chat-ops v39
(`ops_calendar_event._build_event_body`) — một nguồn sự thật cho shape resource.

Gmail send KHÔNG có ở đây: catalog cấm type `email_send` by design (v31 P2) — thư ký
muốn gửi mail phải qua thiết kế riêng, không phải nới catalog.
"""

from __future__ import annotations

from typing import Any


def _calendar_event_args(args: dict[str, str], config: Any) -> dict[str, Any]:
    """Payload `gws_write` từ slots đã qua schema — argv cố định, slots chỉ vào --json.

    Dedup theo (tiêu đề, giờ bắt đầu): nhắc lại cùng một cuộc hẹn không tạo bản sao;
    đổi giờ hoặc đổi tên là sự kiện mới, đúng ngữ nghĩa lịch.
    """
    from my_crew.agent.ops_calendar_event import _build_event_body, calendar_insert_argv

    body = _build_event_body(args)
    return {
        "argv": calendar_insert_argv(body),
        "dedup_hint": f"personal-calendar:{body['summary']}:{body['start']['dateTime']}",
    }


COMMANDS: dict[str, dict] = {
    "tao_lich": {
        "description": (
            "Tạo sự kiện Google Calendar cho chủ nhân — CHỈ khi chủ nhân muốn một SỰ KIỆN "
            "LỊCH có thời điểm cụ thể (họp, hẹn, cuộc gọi, 'đặt lịch…'). Lời dặn dò hay nhờ "
            "nhắc việc ('dặn em nhớ…', 'nhắc anh làm X') KHÔNG phải tạo lịch — thư ký tự "
            "ghi nhớ, hãy trả intent question. args: title (tiêu đề sự kiện), "
            "start (giờ bắt đầu RFC3339 kèm múi giờ, vd 2026-08-05T09:00:00+07:00 — "
            "tính từ mốc BÂY GIỜ khi tin nhắn nói tương đối như 'mai', 'thứ Sáu'), "
            "end (tuỳ chọn, RFC3339), attendees (tuỳ chọn, email cách nhau dấu phẩy)."
        ),
        "type": "gws_write",
        "args_schema": {
            "title": {"required": True, "max_len": 300},
            "start": {"required": True, "max_len": 40,
                      "pattern": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[\d:.+\-Z]*"},
            "end": {"required": False, "max_len": 40,
                    "pattern": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[\d:.+\-Z]*"},
            "attendees": {"required": False, "max_len": 500},
        },
        "build_args": _calendar_event_args,
    },
}
