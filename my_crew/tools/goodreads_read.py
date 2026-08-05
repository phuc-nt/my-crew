"""Goodreads READ — kệ sách công khai qua RSS (thay job Morning Briefing của OpenClaw).

Chỉ đọc, chỉ stdlib, không key mới: Goodreads mở RSS công khai cho từng kệ của một
user_id (`/review/list_rss/<id>?shelf=...`). Feed có sẵn `author_name` / `user_rating` /
`user_read_at` nên không cần bóc HTML trong `<description>`.

Hợp đồng giống gws_read: lỗi mạng/format ném `GoodreadsReadError` để tầng snapshot degrade
thành "(chưa đọc được: …)" — một feed hỏng không bao giờ chặn bản tin sáng.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from datetime import UTC
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

_TIMEOUT_S = 15
_FEED = "https://www.goodreads.com/review/list_rss/{user_id}?shelf={shelf}"
#: Bản tin ngắn — kệ sách dài mấy trăm cuốn vẫn chỉ lấy vài dòng đầu.
_MAX_ITEMS = 10
#: Goodreads trả 403 cho user-agent mặc định của urllib.
_UA = "Mozilla/5.0 (compatible; my-crew personal assistant)"


class GoodreadsReadError(RuntimeError):
    """Đọc Goodreads thất bại (mạng, HTTP lỗi, XML không parse được)."""


def _fetch_items(user_id: str, shelf: str) -> list[ElementTree.Element]:
    """Tải RSS một kệ, trả về danh sách phần tử <item>. Raises GoodreadsReadError."""
    uid = (user_id or "").strip()
    # `isascii()` đi kèm: `isdigit()` một mình nhận cả chữ số Unicode (٣, ３) — không
    # khai thác được (host vẫn cố định) nhưng để lọt thì URL không còn là id thật nữa.
    if not (uid.isascii() and uid.isdigit()):
        raise GoodreadsReadError(f"user_id Goodreads không hợp lệ: {uid[:40]!r}")
    request = urllib.request.Request(  # noqa: S310 — URL do code dựng, luôn https
        _FEED.format(user_id=uid, shelf=shelf), headers={"User-Agent": _UA}
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:  # noqa: S310
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise GoodreadsReadError(f"Goodreads trả HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GoodreadsReadError(f"không gọi được Goodreads: {exc}") from exc
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise GoodreadsReadError(f"RSS Goodreads không parse được: {exc}") from exc
    return root.findall(".//item")


def _text(item: ElementTree.Element, tag: str) -> str:
    node = item.find(tag)
    return (node.text or "").strip() if node is not None else ""


def currently_reading(user_id: str) -> str:
    """Sách đang đọc — "- Tên sách — Tác giả" mỗi dòng."""
    lines = []
    for item in _fetch_items(user_id, "currently-reading")[:_MAX_ITEMS]:
        title = _text(item, "title")
        if not title:
            continue
        author = _text(item, "author_name")
        lines.append(f"- {title[:100]}" + (f" — {author[:60]}" if author else ""))
    return "\n".join(lines) if lines else "(không có)"


def recent_activity(user_id: str, days: int = 7) -> str:
    """Sách đọc xong trong `days` ngày qua, kèm sao nếu CEO đã chấm.

    Kệ `read` sắp theo ngày thêm gần nhất, nên lọc theo `pubDate`; mục nào thiếu/lỗi
    ngày thì bỏ qua thay vì đoán — weekly nói thật hơn là bịa một cuốn cũ thành mới.
    """
    from datetime import datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(days=max(1, min(days, 365)))
    lines = []
    for item in _fetch_items(user_id, "read"):
        published = _text(item, "pubDate")
        try:
            when = parsedate_to_datetime(published)
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if when < cutoff:
            continue
        title = _text(item, "title")
        if not title:
            continue
        rating = _text(item, "user_rating")
        stars = f" ({rating}★)" if rating.isdigit() and int(rating) > 0 else ""
        lines.append(f"- {title[:100]}{stars}")
        if len(lines) >= _MAX_ITEMS:
            break
    return "\n".join(lines) if lines else "(không có)"
