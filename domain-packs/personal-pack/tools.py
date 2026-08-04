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


def _gws_sources() -> dict[str, str]:
    """Lịch 24h tới + email chưa đọc, mỗi nguồn độc lập degrade khi lỗi."""
    from my_crew.tools.gws_read import GwsReadError, calendar_agenda, gmail_triage

    out: dict[str, str] = {}
    for key, fetch in (("calendar_next_24h", calendar_agenda), ("unread_email", gmail_triage)):
        try:
            out[key] = fetch()
        except GwsReadError as exc:
            out[key] = f"(chưa đọc được: {exc})"
    return out


class PersonalToolProvider:
    """Snapshot thuần đọc: ngày giờ (thuần code, luôn có) + gws (degrade êm khi lỗi)."""

    def read(self, kind: str, config: Any, settings: Any) -> dict[str, Any]:
        now = datetime.now().astimezone()
        return {
            "current_time": now.isoformat(timespec="minutes"),
            "weekday": _WEEKDAYS_VI[now.weekday()],
            "upcoming_reminders": _upcoming_reminders(settings),
            **_gws_sources(),
        }


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
