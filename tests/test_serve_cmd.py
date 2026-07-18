"""`my-crew serve` supervisor: spawn set, crash propagation, graceful stop, flag grammar."""

from __future__ import annotations

import signal

from my_crew.entrypoints import serve_cmd


class _FakeProc:
    """Scripted child: returns None from poll() `alive_polls` times, then `rc`."""

    def __init__(self, rc: int | None = None, alive_polls: int = 0):
        self._rc = rc
        self._alive_polls = alive_polls
        self.terminated = False
        self.killed = False

    def poll(self):
        if self.terminated:
            return 0 if self._rc is None else self._rc
        if self._alive_polls > 0:
            self._alive_polls -= 1
            return None
        return self._rc

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return self.poll()


def _quiet_signals(monkeypatch):
    # The supervisor swaps SIGTERM/SIGINT handlers; keep the test process untouched.
    monkeypatch.setattr(signal, "signal", lambda *_a, **_k: signal.SIG_DFL)


def test_mutually_exclusive_flags(capsys):
    assert serve_cmd.run_serve(["--web-only", "--scheduler-only"]) == 2
    assert "mutually exclusive" in capsys.readouterr().err


def test_spawns_both_children_by_default(monkeypatch):
    _quiet_signals(monkeypatch)
    spawned = []

    def _fake_spawn(name):
        spawned.append(name)
        return _FakeProc(rc=0)  # exits immediately → serve returns

    monkeypatch.setattr(serve_cmd, "_spawn", _fake_spawn)
    monkeypatch.setattr(serve_cmd.time, "sleep", lambda s: None)
    serve_cmd.run_serve([])
    assert spawned == ["web", "scheduler"]


def test_web_only_spawns_one(monkeypatch):
    _quiet_signals(monkeypatch)
    spawned = []
    monkeypatch.setattr(
        serve_cmd, "_spawn", lambda name: spawned.append(name) or _FakeProc(rc=0)
    )
    serve_cmd.run_serve(["--web-only"])
    assert spawned == ["web"]


def test_child_crash_propagates_rc_and_stops_sibling(monkeypatch, capsys):
    _quiet_signals(monkeypatch)
    web = _FakeProc(rc=3)  # dies at once with rc 3
    sched = _FakeProc(rc=None, alive_polls=100)  # healthy until terminated
    procs = {"web": web, "scheduler": sched}
    monkeypatch.setattr(serve_cmd, "_spawn", lambda name: procs[name])
    monkeypatch.setattr(serve_cmd.time, "sleep", lambda s: None)
    rc = serve_cmd.run_serve([])
    assert rc == 3
    assert sched.terminated  # sibling brought down
    assert "web exited rc=3" in capsys.readouterr().err


def test_clean_zero_exit_still_reports_failure(monkeypatch):
    # A child exiting rc=0 on its own is NOT normal for a foreground service pair —
    # serve must return non-zero so compose/systemd restart policies fire.
    _quiet_signals(monkeypatch)
    monkeypatch.setattr(serve_cmd, "_spawn", lambda name: _FakeProc(rc=0))
    monkeypatch.setattr(serve_cmd.time, "sleep", lambda s: None)
    assert serve_cmd.run_serve([]) == 1
