"""personal-pack chat-command catalog (v57 3b) — hành động ghi đầu tiên của thư ký.

Một lệnh: tạo sự kiện Google Calendar cho chủ nhân. Native type `gws_write` (vetted tại
pack load), argv CODE-fixed nằm trong `_GWS_ALLOWLIST_PREFIXES` (calendar events insert) —
LLM chỉ điền slot title/start/end/attendees, không bao giờ chạm argv; verb delete/share
bị Lớp A marker chặn trước cả allowlist. Body sự kiện tái dùng builder của chat-ops v39
(`ops_calendar_event._build_event_body`) — một nguồn sự thật cho shape resource.

`gui_email` (v58, đổi kênh 2026-08-04): gửi mail qua `gws gmail +send` (OAuth sẵn của
gws CLI — CEO chốt bỏ SMTP). Cùng đường `gws_write` với tao_lich: secret-scan toàn action
+ marker scan mọi token (body chứa verb kiểu "delete"/"share" bị deny fail-closed — chấp
nhận false-positive, diễn đạt lại được) + allowlist prefix cố định. Helper +send không
nhận attachment — chat không bao giờ gửi file.
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
    """Payload `gws_write` cho `gmail +send` — mail đi bằng OAuth sẵn của gws CLI
    (CEO 2026-08-04: khỏi cần SMTP credential mới). Slots chỉ vào cờ --to/--subject/
    --body, argv prefix CODE-fixed; helper +send không có attachment — đúng posture
    "chat không bao giờ gửi file". Fail RÕ khi máy chưa cài gws.

    Dedup theo (người nhận, tiêu đề, phút): gửi lại cùng mail trong một phút = trùng;
    mail khác tiêu đề/người nhận/lúc khác là mail mới."""
    import shutil
    from datetime import datetime

    if shutil.which("gws") is None:
        raise ValueError(
            "máy chưa cài gws CLI (kênh gửi mail qua OAuth Google) — cài + đăng nhập "
            "gws xong nhắn lại giúp mình."
        )
    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M")
    # chuẩn hoá "a@x.com , b@y.com" → "a@x.com,b@y.com" cho gws (nhận comma-separated)
    to = ",".join(part.strip() for part in args["to"].split(",") if part.strip())
    return {
        "argv": ["gmail", "+send", "--to", to, "--subject", args["subject"],
                 "--body", args["body"]],
        "dedup_hint": f"personal-email:{to}:{args['subject'][:40]}:{stamp}",
    }


COMMANDS: dict[str, dict] = {
    "gui_email": {
        "description": (
            "Gửi một email thay chủ nhân. args: to (địa chỉ email người nhận — "
            "nhiều người thì cách nhau dấu phẩy), "
            "subject (tiêu đề), body (nội dung — soạn trọn vẹn, lịch sự, ký tên chủ nhân). "
            "CHỈ dùng khi chủ nhân bảo gửi/trả lời email rõ ràng; nhờ SOẠN NHÁP thì trả "
            "intent question để soạn cho chủ nhân xem trước."
        ),
        "type": "gws_write",
        "args_schema": {
            # một hoặc nhiều người nhận, cách nhau dấu phẩy (gws +send --to nhận
            # chuỗi comma-separated) — mỗi phần vẫn phải là địa chỉ hợp lệ.
            "to": {"required": True, "max_len": 400,
                   "pattern": (r"[^@\s,]+@[^@\s,]+\.[^@\s,]+"
                               r"(?:\s*,\s*[^@\s,]+@[^@\s,]+\.[^@\s,]+)*")},
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
