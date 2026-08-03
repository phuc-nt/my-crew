"""personal-pack chat-command catalog (v57 3b) — hành động ghi đầu tiên của thư ký.

Một lệnh: tạo sự kiện Google Calendar cho chủ nhân. Native type `gws_write` (vetted tại
pack load), argv CODE-fixed nằm trong `_GWS_ALLOWLIST_PREFIXES` (calendar events insert) —
LLM chỉ điền slot title/start/end/attendees, không bao giờ chạm argv; verb delete/share
bị Lớp A marker chặn trước cả allowlist. Body sự kiện tái dùng builder của chat-ops v39
(`ops_calendar_event._build_event_body`) — một nguồn sự thật cho shape resource.

`gui_email` (v58, CEO chốt 2026-08-03): gửi mail qua native `email_send` — vetted-types
đã nới ĐÚNG type này. Chat không bao giờ gửi file: schema không có `attachment_path`, và
field lạ bị `validate_args` chặn từ vòng ngoài; Lớp A email (secret-scan, shape) nguyên vẹn.
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


def _email_args(args: dict[str, str], config: Any) -> dict[str, Any]:
    """Payload `email_send` từ slots đã qua schema. Fail RÕ khi thiếu SMTP (trả lời được
    cho chủ nhân thay vì lỗi ngầm lúc dispatch); không bao giờ mang attachment_path.

    Dedup theo (người nhận, tiêu đề, phút): gửi lại cùng mail trong một phút = trùng;
    mail khác tiêu đề/người nhận/lúc khác là mail mới."""
    from datetime import datetime

    if getattr(config, "smtp", None) is None:
        raise ValueError(
            "chưa cấu hình SMTP cho agent này (khối smtp: trong profile.yaml + "
            "SMTP_PASSWORD trong .env) — cấu hình xong nhắn lại giúp mình."
        )
    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M")
    return {
        "to": args["to"],
        "subject": args["subject"],
        "body": args["body"],
        "dedup_hint": f"personal-email:{args['to']}:{args['subject'][:40]}:{stamp}",
    }


COMMANDS: dict[str, dict] = {
    "gui_email": {
        "description": (
            "Gửi một email thay chủ nhân. args: to (địa chỉ email người nhận), "
            "subject (tiêu đề), body (nội dung — soạn trọn vẹn, lịch sự, ký tên chủ nhân). "
            "CHỈ dùng khi chủ nhân bảo gửi/trả lời email rõ ràng; nhờ SOẠN NHÁP thì trả "
            "intent question để soạn cho chủ nhân xem trước."
        ),
        "type": "email_send",
        "args_schema": {
            "to": {"required": True, "max_len": 200,
                   "pattern": r"[^@\s]+@[^@\s]+\.[^@\s]+"},
            "subject": {"required": True, "max_len": 200},
            "body": {"required": True, "max_len": 4000},
        },
        "build_args": _email_args,
    },
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
