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


def test_poke_worthy_actions_chain_terminates():
    """v74: a productive tick action pokes the next tick; "none" and dead ends never
    do — that asymmetry is what guarantees every poke chain stops at the first idle
    tick instead of self-sustaining a 5s tick loop."""
    from my_crew.runtime.team_tick_runner import poke_worthy

    for action in ("spawned", "aggregated", "stuck_retry", "stuck_reassigned"):
        assert poke_worthy(action) is True
    for action in ("none", "failed", "stalled", "cap_exceeded", "timeout_escalated",
                   "gave_up"):
        assert poke_worthy(action) is False
