"""Goodreads RSS reader — nguồn "đang đọc gì" cho briefing + hoạt động tuần cho weekly.

Không test nào chạm mạng: fixture XML rút gọn theo hình dạng feed thật (user_id giả),
giữ đúng các element mà parser dựa vào — `author_name`, `user_rating`, `pubDate`.
"""

from __future__ import annotations

import urllib.error
from datetime import UTC

import pytest

from my_crew.tools import goodreads_read
from my_crew.tools.goodreads_read import (
    GoodreadsReadError,
    currently_reading,
    recent_activity,
)


def _feed(items: str) -> bytes:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>{items}'
        "</channel></rss>"
    ).encode()


def _item(title, author="", rating="0", pub_date="Mon, 03 Aug 2026 00:40:59 -0700"):
    return (f"<item><title><![CDATA[{title}]]></title>"
            f"<author_name>{author}</author_name>"
            f"<user_rating>{rating}</user_rating>"
            f"<pubDate><![CDATA[{pub_date}]]></pubDate></item>")


class _Response:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serve(monkeypatch, body, captured=None):
    def _urlopen(request, **kw):
        if captured is not None:
            captured.append(request.full_url)
        return _Response(body)
    monkeypatch.setattr(goodreads_read.urllib.request, "urlopen", _urlopen)


def test_currently_reading_renders_title_and_author(monkeypatch):
    captured = []
    _serve(monkeypatch, _feed(
        _item("Radical Candor: Be a Kickass Boss", "Kim Malone Scott")
        + _item("Bí mật tối thượng", "Dan Brown")
    ), captured)
    out = currently_reading("12345678")
    assert captured == [
        "https://www.goodreads.com/review/list_rss/12345678?shelf=currently-reading"
    ]
    assert out == ("- Radical Candor: Be a Kickass Boss — Kim Malone Scott\n"
                   "- Bí mật tối thượng — Dan Brown")


def test_empty_shelf_says_so(monkeypatch):
    _serve(monkeypatch, _feed(""))
    assert currently_reading("12345678") == "(không có)"


def test_recent_activity_keeps_only_items_inside_the_window(monkeypatch):
    """Kệ `read` chứa cả lịch sử nhiều năm; weekly chỉ được nói về 7 ngày qua."""
    from datetime import datetime, timedelta
    from email.utils import format_datetime

    fresh = format_datetime(datetime.now(UTC) - timedelta(days=2))
    stale = format_datetime(datetime.now(UTC) - timedelta(days=400))
    _serve(monkeypatch, _feed(
        _item("Sách tuần này", rating="5", pub_date=fresh)
        + _item("Sách năm ngoái", rating="4", pub_date=stale)
    ))
    assert recent_activity("12345678", days=7) == "- Sách tuần này (5★)"


def test_recent_activity_omits_stars_when_unrated(monkeypatch):
    from datetime import datetime
    from email.utils import format_datetime

    _serve(monkeypatch, _feed(
        _item("Chưa chấm sao", rating="0", pub_date=format_datetime(datetime.now(UTC)))
    ))
    assert recent_activity("12345678") == "- Chưa chấm sao"


def test_unparseable_pubdate_is_skipped_not_guessed(monkeypatch):
    """Thà bỏ mục hỏng ngày còn hơn đoán — weekly không được bịa sách vào tuần này."""
    _serve(monkeypatch, _feed(_item("Ngày hỏng", pub_date="không phải ngày")))
    assert recent_activity("12345678") == "(không có)"


def test_network_failure_raises_for_caller_to_degrade(monkeypatch):
    def _boom(request, **kw):
        raise urllib.error.URLError("dns fail")
    monkeypatch.setattr(goodreads_read.urllib.request, "urlopen", _boom)
    with pytest.raises(GoodreadsReadError, match="không gọi được"):
        currently_reading("12345678")


def test_http_error_raises(monkeypatch):
    def _boom(request, **kw):
        raise urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
    monkeypatch.setattr(goodreads_read.urllib.request, "urlopen", _boom)
    with pytest.raises(GoodreadsReadError, match="HTTP 403"):
        currently_reading("12345678")


def test_broken_xml_raises(monkeypatch):
    _serve(monkeypatch, b"<rss><channel>")
    with pytest.raises(GoodreadsReadError, match="không parse được"):
        currently_reading("12345678")


def test_non_numeric_user_id_never_reaches_the_network(monkeypatch):
    """user_id đến từ profile.yaml; chặn sớm để không ghép được URL lạ vào feed."""
    def _boom(request, **kw):  # pragma: no cover — phải không bao giờ chạy
        raise AssertionError("không được gọi mạng với user_id sai")
    monkeypatch.setattr(goodreads_read.urllib.request, "urlopen", _boom)
    # "٧٣" là chữ số Ả Rập: `isdigit()` cho qua, nhưng nó không phải id Goodreads nào.
    for bad in ("", "  ", "abc", "12345678?shelf=x", "../etc", "٧٣", "７３"):
        with pytest.raises(GoodreadsReadError, match="không hợp lệ"):
            currently_reading(bad)
