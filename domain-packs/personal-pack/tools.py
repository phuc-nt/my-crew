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
    for key, fetch in (("lich_24h_toi", calendar_agenda), ("email_chua_doc", gmail_triage)):
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
            "bay_gio": now.isoformat(timespec="minutes"),
            "thu": _WEEKDAYS_VI[now.weekday()],
            **_gws_sources(),
        }


#: Required export name — PackRegistry nạp vào Pack.tools.
TOOL_PROVIDER = PersonalToolProvider()
