"""personal-pack chat-command catalog — hành động ghi của thư ký qua chat.

Lịch: tạo (`create_event`), dời/đổi tên (`update_event`), xoá (`delete_event`) sự kiện
Google Calendar. Native type `gws_write` (vetted tại pack load), argv CODE-fixed trong
`_GWS_ALLOWLIST_PREFIXES` — LLM chỉ điền slot, không bao giờ chạm argv. Sửa/xoá resolve
tiêu đề → eventId qua read-only lookup, mơ hồ thì hỏi lại; xoá chỉ sống qua Lớp A khi
argv khớp đúng shape carve-out `_is_calendar_event_delete` (CEO 2026-08-04), verb share/
permission vẫn bị marker chặn vô điều kiện. Body sự kiện tạo mới tái dùng builder chat-ops
v39 (`ops_calendar_event._build_event_body`) — một nguồn sự thật cho shape resource.

`send_email` (v58, kênh gws OAuth): gửi mail qua `gws gmail +send` — cùng đường
`gws_write`: secret-scan toàn action + marker scan mọi token + allowlist prefix cố định.
Helper +send không nhận attachment — chat không bao giờ gửi file.

v61: id lệnh đổi sang English (backend 100% English — CEO 2026-08-04); reply/description
giữ tiếng Việt (lớp người dùng). `assign_task`/`move_task` M12 (v60) đã GỠ — giao việc
đi qua tầng ops orchestration (assign_team_task DAG nhiều agent + confirm), một bề mặt
duy nhất, không để hai đường giao việc song song làm classifier lẫn.
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


def _resolve_event(title: str, at: str = "") -> dict:
    """Tìm ĐÚNG MỘT event 14 ngày tới có tiêu đề chứa `title` (không phân hoa/thường);
    `at` (prefix ngày/giờ RFC3339, vd "2026-08-05" hay "2026-08-05T09:00") lọc thêm
    khi trùng tên.

    0 khớp / nhiều khớp / gws lỗi ⇒ ValueError với thông điệp cho chủ nhân (đường
    build_args→reply có sẵn từ v58) — không bao giờ đoán bừa một event để sửa/xoá."""
    from my_crew.tools.gws_read import GwsReadError, calendar_events_window

    try:
        events = calendar_events_window(title)
    except GwsReadError as exc:
        raise ValueError(f"chưa đọc được lịch ({exc})") from exc
    needle = title.strip().lower()
    matches = [e for e in events if needle in str(e.get("summary", "")).lower()]
    if at.strip():
        prefix = at.strip()
        matches = [
            e for e in matches
            if str((e.get("start") or {}).get("dateTime")
                   or (e.get("start") or {}).get("date", "")).startswith(prefix)
        ]
    if not matches:
        raise ValueError(
            f"không thấy lịch nào tên chứa '{title}' trong 14 ngày tới — anh/chị xem "
            "lại tên giúp mình."
        )
    if len(matches) > 1:
        listing = "; ".join(
            f"'{e.get('summary', '?')}' lúc "
            f"{(e.get('start') or {}).get('dateTime') or (e.get('start') or {}).get('date', '?')}"
            for e in matches[:5]
        )
        raise ValueError(
            f"có {len(matches)} lịch khớp '{title}': {listing}. Anh/chị nói cụ thể "
            "hơn (tên đầy đủ hoặc kèm giờ) giúp mình."
        )
    return matches[0]


def _edit_event_args(args: dict[str, str], config: Any) -> dict[str, Any]:
    """Payload `gws_write` dời/đổi một event: resolve tiêu đề → eventId rồi PATCH.

    new_end vắng ⇒ giữ nguyên THỜI LƯỢNG cũ (end mới = start mới + duration cũ) —
    patch mỗi start mà giữ end cũ dễ thành start > end, API từ chối khó hiểu."""
    import json as _json
    from datetime import datetime

    event = _resolve_event(args["title"], args.get("at", ""))
    body: dict[str, Any] = {}
    if args.get("new_title"):
        body["summary"] = args["new_title"]
    if args.get("new_start"):
        new_start = args["new_start"]
        body["start"] = {"dateTime": new_start}
        if args.get("new_end"):
            body["end"] = {"dateTime": args["new_end"]}
        else:
            old_start = (event.get("start") or {}).get("dateTime")
            old_end = (event.get("end") or {}).get("dateTime")
            try:
                duration = (datetime.fromisoformat(old_end)
                            - datetime.fromisoformat(old_start))
                body["end"] = {
                    "dateTime": (datetime.fromisoformat(new_start) + duration).isoformat()
                }
            except (TypeError, ValueError):
                body["end"] = {"dateTime": new_start}  # event thiếu giờ cũ: end = start,
                # API tự coi là event điểm — vẫn hợp lệ
    if not body:
        raise ValueError("chưa có gì để đổi — cho mình giờ mới hoặc tên mới nhé.")
    params = {"calendarId": "primary", "eventId": str(event["id"])}
    return {
        "argv": ["calendar", "events", "patch", "--params", _json.dumps(params),
                 "--json", _json.dumps(body, ensure_ascii=False)],
        "dedup_hint": f"personal-calendar-edit:{event['id']}:"
                      f"{args.get('new_start', '')}:{args.get('new_title', '')[:40]}",
    }


def _delete_event_args(args: dict[str, str], config: Any) -> dict[str, Any]:
    """Payload `gws_write` xoá một event — argv phải khớp TỪNG BYTE shape carve-out
    `_is_calendar_event_delete` (hard_block v60): đúng 5 phần tử, params chỉ
    calendarId=primary + eventId. Dedup theo eventId: xoá là idempotent."""
    import json as _json

    event = _resolve_event(args["title"], args.get("at", ""))
    params = {"calendarId": "primary", "eventId": str(event["id"])}
    return {
        "argv": ["calendar", "events", "delete", "--params", _json.dumps(params)],
        "dedup_hint": f"personal-calendar-del:{event['id']}",
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


def _set_reminder_args(args: dict[str, str], config: Any) -> dict[str, Any]:
    """Payload `reminder_create` — chat_id là kênh operator của CHÍNH thư ký (không
    bao giờ từ LLM args): tin nhắc chỉ có thể quay về chủ nhân."""
    telegram = getattr(config, "telegram", None)
    if telegram is None:
        raise ValueError("chưa cấu hình Telegram — không có kênh để nhắc")
    chat_id = str(telegram.ops_operator_id or telegram.chat_ids[0])
    return {
        "chat_id": chat_id,
        "text": args["text"].strip(),
        "due_at": args["at"].strip(),
        "dedup_hint": f"personal-reminder-set:{args['at'].strip()}:{args['text'].strip()[:60]}",
    }


def _cancel_reminder_args(args: dict[str, str], config: Any) -> dict[str, Any]:
    return {
        "reminder_id": int(args["reminder_id"]),
        "dedup_hint": f"personal-reminder-cancel:{args['reminder_id']}",
    }


COMMANDS: dict[str, dict] = {
    "set_reminder": {
        "description": (
            "Đặt nhắc hẹn giờ MỘT LẦN cho chủ nhân ('3h nhắc anh gọi X') — đúng giờ "
            "thư ký sẽ nhắn Telegram. args: at (thời điểm nhắc RFC3339 kèm múi giờ, "
            "vd 2026-08-05T15:00:00+07:00 — tính từ mốc BÂY GIỜ khi nói tương đối như "
            "'3h chiều', 'mai'), text (nội dung nhắc, ngắn gọn). CHỈ dùng khi chủ nhân "
            "muốn được NHẮC vào một thời điểm; sự kiện lịch (họp/hẹn) thì dùng "
            "create_event."
        ),
        "type": "reminder_create",
        "args_schema": {
            "at": {"required": True, "max_len": 40,
                   "pattern": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[\d:.+\-Z]*"},
            "text": {"required": True, "max_len": 500},
        },
        "build_args": _set_reminder_args,
    },
    "cancel_reminder": {
        "description": (
            "Huỷ MỘT nhắc hẹn giờ đã đặt. args: reminder_id (số id của nhắc — có trong "
            "câu trả lời lúc đặt và trong danh sách upcoming_reminders). Chủ nhân hỏi "
            "'sắp nhắc gì' thì trả lời từ snapshot, không cần lệnh."
        ),
        "type": "reminder_cancel",
        "args_schema": {
            "reminder_id": {"required": True, "max_len": 10, "pattern": r"[0-9]+"},
        },
        "build_args": _cancel_reminder_args,
    },
    "send_email": {
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
    "create_event": {
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
    "update_event": {
        "description": (
            "Dời giờ hoặc đổi tên MỘT sự kiện lịch ĐÃ CÓ của chủ nhân. args: title "
            "(tên sự kiện hiện tại, đủ để nhận ra duy nhất), new_start (tuỳ chọn — giờ "
            "bắt đầu mới RFC3339 kèm múi giờ, tính từ mốc BÂY GIỜ khi nói tương đối), "
            "new_end (tuỳ chọn), new_title (tuỳ chọn — tên mới), at (tuỳ chọn — ngày "
            "hoặc giờ HIỆN TẠI của lịch để phân biệt khi trùng tên, dạng 2026-08-05 "
            "hoặc 2026-08-05T09:00). CHỈ dùng khi chủ nhân muốn thay đổi lịch đã tồn "
            "tại; tạo mới thì dùng create_event."
        ),
        "type": "gws_write",
        "args_schema": {
            "title": {"required": True, "max_len": 300},
            "new_start": {"required": False, "max_len": 40,
                          "pattern": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[\d:.+\-Z]*"},
            "new_end": {"required": False, "max_len": 40,
                        "pattern": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[\d:.+\-Z]*"},
            "new_title": {"required": False, "max_len": 300},
            "at": {"required": False, "max_len": 20,
                   "pattern": r"\d{4}-\d{2}-\d{2}[T\d:]*"},
        },
        "build_args": _edit_event_args,
    },
    "delete_event": {
        "description": (
            "Xoá MỘT sự kiện lịch của chủ nhân. args: title (tên sự kiện, đủ để nhận "
            "ra duy nhất), at (tuỳ chọn — ngày hoặc giờ của lịch để phân biệt khi "
            "trùng tên, dạng 2026-08-05 hoặc 2026-08-05T09:00). CHỈ dùng khi chủ nhân "
            "nói rõ xoá/hủy lịch đó; nghi ngờ thì trả intent question hỏi lại — xoá "
            "không hoàn tác được."
        ),
        "type": "gws_write",
        "args_schema": {
            "title": {"required": True, "max_len": 300},
            "at": {"required": False, "max_len": 20,
                   "pattern": r"\d{4}-\d{2}-\d{2}[T\d:]*"},
        },
        "build_args": _delete_event_args,
    },
}
