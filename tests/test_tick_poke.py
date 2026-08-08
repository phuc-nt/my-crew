"""v74 phase 2: the tick poke file — the touch/read pair both sides of the signal use."""

from __future__ import annotations

import my_crew.config.settings as settings
from my_crew.runtime import tick_poke


def test_touch_creates_file_and_mtime_becomes_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    assert tick_poke.poke_mtime() is None  # no file yet → no signal, not an error
    tick_poke.touch_poke()
    assert (tmp_path / "tick.poke").exists()
    assert tick_poke.poke_mtime() is not None


def test_touch_failure_is_swallowed(monkeypatch):
    def _boom():
        raise OSError("disk full")

    monkeypatch.setattr(tick_poke, "poke_path", _boom)
    tick_poke.touch_poke()  # must not raise — degrade to the 60s cadence
