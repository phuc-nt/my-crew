"""personal-pack chat-command catalog (v57 3b) — hành động ghi đầu tiên của thư ký.

Lịch: tạo (`tao_lich`), dời/đổi tên (`doi_lich`), xoá (`xoa_lich`) sự kiện Google
Calendar. Native type `gws_write` (vetted tại pack load), argv CODE-fixed trong
`_GWS_ALLOWLIST_PREFIXES` — LLM chỉ điền slot, không bao giờ chạm argv. Sửa/xoá resolve
tiêu đề → eventId qua read-only lookup, mơ hồ thì hỏi lại; xoá chỉ sống qua Lớp A khi
argv khớp đúng shape carve-out `_is_calendar_event_delete` (CEO 2026-08-04), verb share/
permission vẫn bị marker chặn vô điều kiện. Body sự kiện tạo mới tái dùng builder chat-ops
v39 (`ops_calendar_event._build_event_body`) — một nguồn sự thật cho shape resource.

`gui_email` (v58, đổi kênh 2026-08-04): gửi mail qua `gws gmail +send` (OAuth sẵn của
gws CLI — CEO chốt bỏ SMTP). Cùng đường `gws_write` với tao_lich: secret-scan toàn action
+ marker scan mọi token (body chứa verb kiểu "delete"/"share" bị deny fail-closed — chấp
nhận false-positive, diễn đạt lại được) + allowlist prefix cố định. Helper +send không
nhận attachment — chat không bao giờ gửi file.
"""

from __future__ import annotations

from typing import Any


def _roster_hint() -> str:
    """Danh sách mã đồng nghiệp giao được việc, chèn vào description lúc pack load —
    classifier chỉ thấy catalog nên mã agent phải nằm ngay trong mô tả lệnh. Registry
    vắng (môi trường test) ⇒ fallback text tĩnh, không nổ import."""
    try:
        from my_crew.agent.team_task_roster import assignable_staff

        ids = ", ".join(f"'{aid}'" for aid, _domain in assignable_staff())
        return ids or "xem bảng nhân sự"
    except Exception:  # noqa: BLE001 — thiếu registry/store chỉ mất gợi ý, không mất lệnh
        return "xem bảng nhân sự"


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


def _resolve_event(title: str, luc: str = "") -> dict:
    """Tìm ĐÚNG MỘT event 14 ngày tới có tiêu đề chứa `title` (không phân hoa/thường);
    `luc` (prefix ngày/giờ RFC3339, vd "2026-08-05" hay "2026-08-05T09:00") lọc thêm
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
    if luc.strip():
        prefix = luc.strip()
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

    event = _resolve_event(args["title"], args.get("luc", ""))
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

    event = _resolve_event(args["title"], args.get("luc", ""))
    params = {"calendarId": "primary", "eventId": str(event["id"])}
    return {
        "argv": ["calendar", "events", "delete", "--params", _json.dumps(params)],
        "dedup_hint": f"personal-calendar-del:{event['id']}",
    }


def _create_task_args(args: dict[str, str], config: Any) -> dict[str, Any]:
    """Payload `team_task_create` — creator là chính thư ký (handler actor-bound đóng
    identity tại call site, payload không có field actor để giả). Dedup state-bearing:
    cùng (assignee, title) trong cùng phút mới coi là trùng — giao lại hôm sau là thẻ mới."""
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
    """Payload `team_task_move`. Dedup theo (thẻ, trạng thái đích, phút): move→reopen→
    move lại là ba key, không bị nuốt thành trùng."""
    from datetime import datetime

    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M")
    return {
        "task_id": args["task_id"],
        "status": args["status"],
        "dedup_hint": f"move:{args['task_id']}:{args['status']}:{stamp}",
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
    # --- v60: sửa/xoá lịch (CEO 2026-08-04) ---
    "doi_lich": {
        "description": (
            "Dời giờ hoặc đổi tên MỘT sự kiện lịch ĐÃ CÓ của chủ nhân. args: title "
            "(tên sự kiện hiện tại, đủ để nhận ra duy nhất), new_start (tuỳ chọn — giờ "
            "bắt đầu mới RFC3339 kèm múi giờ, tính từ mốc BÂY GIỜ khi nói tương đối), "
            "new_end (tuỳ chọn), new_title (tuỳ chọn — tên mới), luc (tuỳ chọn — ngày "
            "hoặc giờ HIỆN TẠI của lịch để phân biệt khi trùng tên, dạng 2026-08-05 "
            "hoặc 2026-08-05T09:00). CHỈ dùng khi chủ nhân muốn thay đổi lịch đã tồn "
            "tại; tạo mới thì dùng tao_lich."
        ),
        "type": "gws_write",
        "args_schema": {
            "title": {"required": True, "max_len": 300},
            "new_start": {"required": False, "max_len": 40,
                          "pattern": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[\d:.+\-Z]*"},
            "new_end": {"required": False, "max_len": 40,
                        "pattern": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[\d:.+\-Z]*"},
            "new_title": {"required": False, "max_len": 300},
            "luc": {"required": False, "max_len": 20,
                    "pattern": r"\d{4}-\d{2}-\d{2}[T\d:]*"},
        },
        "build_args": _edit_event_args,
    },
    "xoa_lich": {
        "description": (
            "Xoá MỘT sự kiện lịch của chủ nhân. args: title (tên sự kiện, đủ để nhận "
            "ra duy nhất), luc (tuỳ chọn — ngày hoặc giờ của lịch để phân biệt khi "
            "trùng tên, dạng 2026-08-05 hoặc 2026-08-05T09:00). CHỈ dùng khi chủ nhân "
            "nói rõ xoá/hủy lịch đó; nghi ngờ thì trả intent question hỏi lại — xoá "
            "không hoàn tác được."
        ),
        "type": "gws_write",
        "args_schema": {
            "title": {"required": True, "max_len": 300},
            "luc": {"required": False, "max_len": 20,
                    "pattern": r"\d{4}-\d{2}-\d{2}[T\d:]*"},
        },
        "build_args": _delete_event_args,
    },
    # --- v60: cổng điều phối — thư ký giao việc cho crew (CEO 2026-08-04) ---
    "giao_viec": {
        "description": (
            "Giao một việc cho đồng nghiệp trong công ty thay chủ nhân — tạo thẻ việc "
            "đội, điều phối viên sẽ lên kế hoạch và chạy. args: title (tiêu đề việc, "
            "ngắn gọn), assignee (MÃ agent nhận việc — một trong: " + _roster_hint() +
            "), detail (tuỳ chọn, mô tả/yêu cầu thêm). CHỈ dùng khi chủ nhân bảo "
            "giao/nhờ team làm việc gì đó."
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
    "chuyen_the": {
        "description": (
            "Chuyển trạng thái một thẻ việc đội mà thư ký tham gia (người tạo/PIC/"
            "người nhận bước) — dùng để hủy việc vừa giao (status cancelled) hoặc mở "
            "lại. args: task_id (mã thẻ), status (một trong: planning, open, running, "
            "done, cancelled, stalled)."
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
