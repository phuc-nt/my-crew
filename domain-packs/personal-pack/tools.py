"""personal-pack ToolProvider (v57) — bối cảnh ngày cho thư ký.

Seam read duy nhất của pack: `read("briefing")` trả bối cảnh thời gian hiện tại theo
múi giờ máy (giờ của chủ nhân). Đây cũng là snapshot ground cho chat DM (đường Q&A M11
lấy kind đầu tiên của pack). Các nguồn ngoài (lịch, email, drive) sẽ nối vào chính
provider này ở phase sau — chat và briefing tự giàu lên mà không đổi seam.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

#: Thứ trong tuần tiếng Việt theo `date.weekday()` (0 = thứ Hai).
_WEEKDAYS_VI = ("Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật")


class PersonalToolProvider:
    """Bối cảnh tối thiểu, thuần code (không LLM, không mạng) — luôn chạy được offline."""

    def read(self, kind: str, config: Any, settings: Any) -> dict[str, Any]:
        now = datetime.now().astimezone()
        return {
            "bay_gio": now.isoformat(timespec="minutes"),
            "thu": _WEEKDAYS_VI[now.weekday()],
            "nguon_da_noi": [],  # phase sau: "calendar", "gmail", "drive"…
            "ghi_chu": "Chưa nối nguồn ngoài — chỉ biết ngày giờ và trí nhớ của chính mình.",
        }


#: Required export name — PackRegistry nạp vào Pack.tools.
TOOL_PROVIDER = PersonalToolProvider()
