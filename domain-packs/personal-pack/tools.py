"""personal-pack ToolProvider (v57) — bối cảnh ngày + Google Workspace cho thư ký.

Seam read duy nhất của pack: `read(kind)` trả snapshot ground cho CẢ chat DM (đường Q&A
M11 lấy kind đầu tiên trong `reports:`) lẫn briefing/weekly (perceive của push graph).

Google Workspace đọc qua CLI `gws` (OAuth của chính CLI, không key mới trong .env) — pack
personal theo định nghĩa là thư ký của chủ máy nên KHÔNG cần cờ bật: máy có `gws` đã auth
thì lịch + email tự vào snapshot; thiếu CLI/hết hạn OAuth thì degrade thành chuỗi
"(chưa đọc được: …)" — thư ký nói thật là chưa xem được, không bao giờ crash vòng trả lời.
Drive không nằm trong snapshot (cần query cụ thể — để cho tool-loop team-step, v39).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

#: Thứ trong tuần tiếng Việt theo `date.weekday()` (0 = thứ Hai).
_WEEKDAYS_VI = ("Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật")


def _read(fetch) -> str:
    """Gọi một nguồn; mọi lỗi thành chuỗi nói-thật thay vì ném lên vòng trả lời."""
    try:
        return fetch()
    except Exception as exc:  # noqa: BLE001 — snapshot phải render dù nguồn nào hỏng
        return f"(chưa đọc được: {exc})"


def _soft(key: str, fetch) -> tuple[str, str]:
    """`_read` ở dạng cặp (key, value) để dựng thẳng dict nhiều nguồn."""
    return key, _read(fetch)


#: Khoá gws trong snapshot ngày — giữ nguyên khi tắt (giá trị "(chưa cấu hình)") để
#: prompt không đổi hình dạng giữa agent bật và agent tắt.
_GWS_DAILY_KEYS = ("calendar_next_24h", "unread_email", "pending_tasks")


def _gws_enabled(config: Any) -> bool:
    """Cờ `gws_enabled` của profile; thiếu cờ nghĩa là bật (mặc định cũ)."""
    return bool(getattr(config, "gws_enabled", True))


def _gws_sources(config: Any) -> dict[str, str]:
    """Lịch 24h tới + email chưa đọc + việc còn treo, mỗi nguồn độc lập degrade khi lỗi.

    `gws_enabled: false` ⇒ đủ khoá nhưng "(chưa cấu hình)", và KHÔNG import/chạy `gws`:
    agent tắt không được đụng vào hộp thư hay lịch của chủ máy dù CLI vẫn đang auth.
    """
    if not _gws_enabled(config):
        return {key: "(chưa cấu hình)" for key in _GWS_DAILY_KEYS}
    from my_crew.tools.gws_read import calendar_agenda, gmail_triage, tasks_pending

    return dict(
        _soft(key, fetch) for key, fetch in (
            ("calendar_next_24h", calendar_agenda),
            ("unread_email", gmail_triage),
            ("pending_tasks", tasks_pending),
        )
    )


def _goodreads_user_id(config: Any) -> str:
    """`goodreads_user_id` của profile; rỗng nghĩa là agent này không khai kệ sách."""
    return str(getattr(config, "goodreads_user_id", "") or "").strip()


def _reading_now(config: Any) -> str:
    user_id = _goodreads_user_id(config)
    if not user_id:
        return "(chưa cấu hình)"
    from my_crew.tools.goodreads_read import currently_reading

    return _read(lambda: currently_reading(user_id))


def _weekly_sources(config: Any) -> dict[str, str]:
    """Dải tuần — chỉ weekly-review mới trả giá cho mấy lượt đọc này.

    Hai nguồn lịch/việc đi qua `gws` nên tắt theo `gws_enabled`; kệ sách và bài học
    không dính Google nên vẫn đọc bình thường.
    """
    gws_on = _gws_enabled(config)
    if gws_on:
        from my_crew.tools.gws_read import calendar_events_window, tasks_completed

    user_id = _goodreads_user_id(config)

    def _books_7d() -> str:
        if not user_id:
            return "(chưa cấu hình)"
        from my_crew.tools.goodreads_read import recent_activity

        return recent_activity(user_id, days=7)

    def _calendar_7d() -> str:
        if not gws_on:
            return "(chưa cấu hình)"
        lines = []
        for event in calendar_events_window(days=7)[:15]:
            start = event.get("start") or {}
            # Sự kiện cả ngày không có `dateTime`, chỉ có `date` — thiếu nhánh này thì
            # mọi lịch cả ngày trong tuần hiện ra không kèm ngày nào.
            when = (start.get("dateTime") or start.get("date") or "")[:16]
            title = (event.get("summary") or "(không tên)")[:80]
            lines.append(f"- {title}" + (f" ({when})" if when else ""))
        return "\n".join(lines) if lines else "(không có)"

    def _tasks_done_7d() -> str:
        if not gws_on:
            return "(chưa cấu hình)"
        return tasks_completed(days=7)

    return dict(
        _soft(key, fetch) for key, fetch in (
            ("calendar_next_7d", _calendar_7d),
            ("tasks_completed_7d", _tasks_done_7d),
            ("goodreads_activity_7d", _books_7d),
            ("lessons", _recent_lessons),
        )
    )


def _recent_lessons() -> str:
    """Bài học phản tư (v69) — weekly nhìn lại tuần dựa trên cái đội đã rút ra."""
    from my_crew.agent.ops_list_lessons import run_list_lessons

    return run_list_lessons({}).strip() or "(không có)"


class PersonalToolProvider:
    """Snapshot thuần đọc: ngày giờ (thuần code, luôn có) + gws (degrade êm khi lỗi).

    `kind` quyết định dải dữ liệu: mọi kind lấy bối cảnh ngày (chat Q&A cũng ground
    trên đây), riêng `weekly-review` cộng thêm dải 7 ngày — lịch tuần tới, việc đã
    xong, sách đọc trong tuần, bài học. Briefing KHÔNG gọi nhóm tuần: mỗi nguồn là một
    lượt CLI/mạng, bản tin sáng không cần trả giá đó.
    """

    def read(self, kind: str, config: Any, settings: Any) -> dict[str, Any]:
        now = datetime.now().astimezone()
        gws = _gws_sources(config)
        # Hộp thư là nguồn DUY NHẤT phình to (đo thật: ~4.2k/5.5k ký tự) và
        # `render_snapshot` cắt phẳng theo vị trí ở cuối chuỗi JSON. Nguồn nào đứng sau
        # nó sẽ bị cắt trước — nên email đi CUỐI: một ngày hộp thư dày thì mất phần đuôi
        # của danh sách email (thừa sẵn), chứ không mất trọn nhóm tuần của weekly.
        bulky = {"unread_email": gws.pop("unread_email", "(không có)")}
        snapshot: dict[str, Any] = {
            "current_time": now.isoformat(timespec="minutes"),
            "weekday": _WEEKDAYS_VI[now.weekday()],
            "upcoming_reminders": _upcoming_reminders(settings),
            "reading_now": _reading_now(config),
            **gws,
        }
        if kind == "weekly-review":
            snapshot.update(_weekly_sources(config))
        snapshot.update(bulky)
        return snapshot


def _upcoming_reminders(settings: Any) -> str:
    """Pending timed reminders (v65) — "#id · giờ · nội dung" per line so chat can
    answer "sắp nhắc gì?" and the CEO can cancel by the id. Degrade-soft like every
    other snapshot source; "(không có)" khi trống."""
    try:
        from pathlib import Path

        from my_crew.runtime.reminder_store import ReminderStore, reminders_db_path

        path = reminders_db_path(Path(settings.data_dir))
        if not path.exists():
            return "(không có)"
        store = ReminderStore(path)
        try:
            rows = store.list_pending()
        finally:
            store.close()
        if not rows:
            return "(không có)"
        return "\n".join(f"#{r['id']} · {r['due_at']} · {r['text'][:80]}" for r in rows[:10])
    except Exception as exc:  # noqa: BLE001 — snapshot must render even if store hiccups
        return f"(chưa đọc được: {exc})"


#: Required export name — PackRegistry nạp vào Pack.tools.
TOOL_PROVIDER = PersonalToolProvider()
