"""v57 P5: daily notes + chat remember + nạp context. Offline (extractor inject).

Load-bearing properties:

- append/nạp đúng layout `profiles/<id>/memory/YYYY-MM-DD.md`; cùng ngày append dồn;
  cap/ngày chặn phình; cửa sổ N ngày cắt NGUYÊN FILE từ cũ nhất khi vượt cap context.
- Đường ghi bị giam trong profile dir: profile_id lạ (traversal) bị từ chối.
- `resolve_memory_text`: không opt-in ⇒ byte-identical MEMORY.md; opt-in ⇒ ghép notes.
- Chat remember: chỉ chạy khi opt-in + không dry-run + reply đã executed; extractor rỗng
  ⇒ không ghi; lỗi bên trong ⇒ nuốt + trả 0 (không phá lượt chat).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from my_crew.agent.chat_memory import remember_chat_exchange
from my_crew.memory import daily_notes as dn
from my_crew.memory.provider import MemoryConfig, parse_memory_config, resolve_memory_text

_NOW = datetime(2026, 8, 3, 21, 5).astimezone()


# --- daily notes file ops ---


def test_append_creates_dated_file_and_accumulates(tmp_path):
    n1 = dn.append_daily_note("tk", ["dặn gửi báo giá cho anh Nam"], now=_NOW,
                              profiles_dir=tmp_path)
    n2 = dn.append_daily_note("tk", ["hẹn cà phê thứ Sáu"], now=_NOW, profiles_dir=tmp_path)
    assert (n1, n2) == (1, 1)
    text = (tmp_path / "tk" / "memory" / "2026-08-03.md").read_text(encoding="utf-8")
    assert text.startswith("# Nhật ký 2026-08-03")
    assert "- 21:05 dặn gửi báo giá cho anh Nam" in text
    assert "- 21:05 hẹn cà phê thứ Sáu" in text


def test_append_skips_when_day_file_full(tmp_path):
    folder = tmp_path / "tk" / "memory"
    folder.mkdir(parents=True)
    (folder / "2026-08-03.md").write_text("x" * dn._DAY_FILE_CAP_CHARS, encoding="utf-8")
    assert dn.append_daily_note("tk", ["thêm nữa"], now=_NOW, profiles_dir=tmp_path) == 0


def test_append_rejects_path_traversal_profile_id(tmp_path):
    with pytest.raises(ValueError, match="profile_id"):
        dn.append_daily_note("../evil", ["x"], now=_NOW, profiles_dir=tmp_path)


def test_recent_notes_window_and_cap(tmp_path):
    folder = tmp_path / "tk" / "memory"
    folder.mkdir(parents=True)
    (folder / "2026-07-20.md").write_text("quá cũ — ngoài cửa sổ 7 ngày", encoding="utf-8")
    (folder / "2026-07-28.md").write_text("ngày đầu cửa sổ", encoding="utf-8")
    (folder / "2026-08-02.md").write_text("hôm qua", encoding="utf-8")
    (folder / "2026-08-03.md").write_text("hôm nay", encoding="utf-8")
    (folder / "notes.txt").write_text("file lạ — bỏ qua", encoding="utf-8")
    out = dn.recent_notes_text("tk", now=_NOW, profiles_dir=tmp_path)
    assert "quá cũ" not in out and "file lạ" not in out
    assert out.index("ngày đầu cửa sổ") < out.index("hôm qua") < out.index("hôm nay")
    capped = dn.recent_notes_text("tk", now=_NOW, profiles_dir=tmp_path, cap_chars=10)
    assert capped == "hôm nay"  # cắt nguyên file từ phía cũ


# --- provider context ---


def _loaded(tmp_path, *, daily: bool, memory_md: str = "fact tĩnh"):
    return SimpleNamespace(
        profile_id="tk", memory=memory_md, soul="", project="",
        memory_config=MemoryConfig(provider="static", daily_notes=daily),
    )


def test_resolve_memory_text_without_optin_is_unchanged(tmp_path, monkeypatch):
    loaded = _loaded(tmp_path, daily=False)
    assert resolve_memory_text(loaded) == "fact tĩnh"


def test_resolve_memory_text_appends_recent_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "my_crew.memory.daily_notes.recent_notes_text",
        lambda pid, **kw: "# Nhật ký 2026-08-03\n- 21:05 dặn X",
    )
    out = resolve_memory_text(_loaded(tmp_path, daily=True))
    assert out.startswith("fact tĩnh")
    assert "NHẬT KÝ GẦN ĐÂY" in out and "dặn X" in out


def test_parse_memory_config_daily_notes():
    assert parse_memory_config({"daily_notes": True}).daily_notes is True
    assert parse_memory_config({}).daily_notes is False
    with pytest.raises(RuntimeError, match="daily_notes"):
        parse_memory_config({"daily_notes": "yes"})


# --- chat remember ---


def _settings(dry: bool):
    return SimpleNamespace(dry_run=dry)


def test_remember_chat_writes_note_and_mirror(tmp_path, monkeypatch):
    monkeypatch.setattr("my_crew.profile.loader._PROFILES_DIR", tmp_path)
    loaded = _loaded(tmp_path, daily=True)
    n = remember_chat_exchange(
        loaded, _settings(dry=False), question="dặn em gửi báo giá cho anh Nam thứ Ba",
        reply="Dạ em ghi nhớ rồi ạ.", extractor=lambda text: ["Gửi báo giá cho anh Nam thứ Ba"],
    )
    assert n == 1
    note = (tmp_path / "tk" / "memory").glob("*.md")
    assert any("báo giá" in p.read_text(encoding="utf-8") for p in note)
    memory_md = (tmp_path / "tk" / "MEMORY.md").read_text(encoding="utf-8")
    assert "Gửi báo giá cho anh Nam thứ Ba" in memory_md  # mirror section


def test_remember_chat_gates(tmp_path):
    on = _loaded(tmp_path, daily=True)
    off = _loaded(tmp_path, daily=False)
    boom = lambda text: (_ for _ in ()).throw(RuntimeError("extractor chết"))  # noqa: E731
    assert remember_chat_exchange(off, _settings(dry=False), question="q", reply="r",
                                  extractor=lambda t: ["x"]) == 0  # không opt-in
    assert remember_chat_exchange(on, _settings(dry=True), question="q", reply="r",
                                  extractor=lambda t: ["x"]) == 0  # dry-run
    assert remember_chat_exchange(on, _settings(dry=False), question="q", reply="r",
                                  extractor=lambda t: []) == 0  # không có gì đáng nhớ
    assert remember_chat_exchange(on, _settings(dry=False), question="q", reply="r",
                                  extractor=boom) == 0  # lỗi ⇒ nuốt, không raise
