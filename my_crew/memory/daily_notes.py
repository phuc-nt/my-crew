"""Daily notes (v57 P5) — nhật ký thô theo ngày của một agent, kiểu Pong.

`profiles/<id>/memory/YYYY-MM-DD.md`: mỗi lượt việc đáng nhớ append vài dòng (prefix giờ);
mỗi run nạp lại các ngày gần nhất vào context (qua `resolve_memory_text`). Khác MEMORY.md
(mirror curated, cap 50 fact): notes là dòng thời gian thô, tự hết hạn khỏi context sau
`_DEFAULT_RECENT_DAYS` ngày — file cũ để nguyên trên đĩa (nhỏ, không GC vội).

An toàn:
- Tên file sinh TỪ NGÀY, không bao giờ từ input người dùng; `profile_id` validate regex
  nên đường ghi không thể trỏ ra ngoài `profiles/<id>/memory/`.
- Cap kích thước/ngày: một trận chat dài không phình file vô hạn (quá cap → bỏ qua, log).
- Internal agent state — KHÔNG qua Action Gateway (cùng lý do MEMORY.md mirror: gateway
  chỉ quản mutation RA NGOÀI).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from my_crew.profile.loader import profile_memory_path

logger = logging.getLogger(__name__)

#: Trần ký tự MỘT file ngày — vượt là dấu hiệu ghi quá tay, dừng ghi thay vì phình.
_DAY_FILE_CAP_CHARS = 4000
#: Mặc định nạp lại bao nhiêu ngày gần nhất vào context.
_DEFAULT_RECENT_DAYS = 7
#: Trần tổng ký tự phần notes trong context (cắt từ ngày cũ nhất).
_DEFAULT_CONTEXT_CAP = 8000

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_NOTE_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


def daily_notes_dir(profile_id: str, *, profiles_dir: Path | None = None) -> Path:
    """`profiles/<id>/memory/` — suy từ `profile_memory_path` (một nguồn sự thật về layout)."""
    if not _ID_RE.fullmatch(profile_id or ""):
        raise ValueError(f"profile_id không hợp lệ: {profile_id!r}")
    return profile_memory_path(profile_id, profiles_dir=profiles_dir).parent / "memory"


def append_daily_note(
    profile_id: str,
    lines: list[str],
    *,
    now: datetime | None = None,
    profiles_dir: Path | None = None,
) -> int:
    """Append các dòng (prefix giờ) vào file của NGÀY HÔM NAY. Trả số dòng đã ghi.

    File đầy (quá cap) → ghi 0 dòng + warning: mất một note tốt hơn là một file
    phình vô hạn được nạp lại vào context mỗi run.
    """
    cleaned = [ln.strip() for ln in lines if ln and ln.strip()]
    if not cleaned:
        return 0
    now = now or datetime.now().astimezone()
    path = daily_notes_dir(profile_id, profiles_dir=profiles_dir) / f"{now.date().isoformat()}.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if len(existing) >= _DAY_FILE_CAP_CHARS:
        logger.warning("daily note %s đầy (%d ký tự) — bỏ qua %d dòng",
                       path.name, len(existing), len(cleaned))
        return 0
    stamp = now.strftime("%H:%M")
    block = "".join(f"- {stamp} {ln}\n" for ln in cleaned)
    header = "" if existing else f"# Nhật ký {now.date().isoformat()}\n\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(header + block)
    return len(cleaned)


def recent_notes_text(
    profile_id: str,
    *,
    days: int = _DEFAULT_RECENT_DAYS,
    cap_chars: int = _DEFAULT_CONTEXT_CAP,
    now: datetime | None = None,
    profiles_dir: Path | None = None,
) -> str:
    """Ghép các file ngày trong cửa sổ `days` gần nhất (cũ trước → mới sau), cắt về cap.

    Cắt NGUYÊN FILE từ phía cũ nhất khi vượt cap — một ngày bị cắt nửa chừng dễ gây
    hiểu nhầm hơn là vắng hẳn.
    """
    now = now or datetime.now().astimezone()
    folder = daily_notes_dir(profile_id, profiles_dir=profiles_dir)
    if not folder.exists():
        return ""
    cutoff = (now.date().toordinal()) - days + 1
    picked: list[tuple[str, str]] = []
    for path in sorted(folder.iterdir()):
        if not _NOTE_FILE_RE.fullmatch(path.name):
            continue  # file lạ trong thư mục — không phải note, bỏ qua
        try:
            day = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if day.toordinal() >= cutoff and day <= now.date():
            picked.append((path.stem, path.read_text(encoding="utf-8").strip()))
    while picked and sum(len(t) for _, t in picked) > cap_chars:
        picked.pop(0)  # bỏ ngày cũ nhất trước
    return "\n\n".join(text for _, text in picked)
