"""`team_tick_runner._kill_pid`: PID-reuse-guarded SIGKILL — a
lease-expired step's recorded `child_pid` may, by the time the lease actually expires,
have been reaped and reassigned by the OS to an unrelated process. `_kill_pid` must
verify the live process is still THIS step's worker (via its `attempt_id` appearing in
the process's command line) before signaling it.
"""

from __future__ import annotations

import my_crew.runtime.team_tick_runner as mod


def test_kill_pid_signals_when_command_line_contains_attempt_id(monkeypatch):
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(mod.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    mod._kill_pid(
        4242, "attempt-abc",
        ps_command_line=lambda pid: (
            "/usr/bin/python3 -m my_crew.runtime.worker --attempt-id attempt-abc --task-id t1"
        ),
    )
    assert killed == [(4242, 9)]


def test_kill_pid_skips_when_command_line_has_no_attempt_id_match(monkeypatch):
    """The pid was reused by an unrelated process — the command line exists but does
    not mention this step's attempt_id. Must NOT kill a stranger."""
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(mod.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    mod._kill_pid(
        4242, "attempt-abc",
        ps_command_line=lambda pid: "/usr/bin/some-unrelated-daemon --flag",
    )
    assert killed == []


def test_kill_pid_skips_when_process_already_gone(monkeypatch):
    """`ps` returns empty output for a pid that no longer exists — no identity to
    verify, so skip the kill (the caller marks the step `timeout` regardless)."""
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(mod.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    mod._kill_pid(4242, "attempt-abc", ps_command_line=lambda pid: "")
    assert killed == []


def test_kill_pid_swallows_already_dead_race_after_identity_confirmed(monkeypatch):
    """Identity check passed, but the process died in the tiny window before the
    actual kill signal — `ProcessLookupError` must be swallowed, not raised."""

    def _raise(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(mod.os, "kill", _raise)

    mod._kill_pid(
        4242, "attempt-abc",
        ps_command_line=lambda pid: "worker --attempt-id attempt-abc",
    )  # must not raise


def test_ps_command_line_returns_empty_string_on_subprocess_failure(monkeypatch):
    """A missing/erroring `ps` binary degrades to empty output (treated as "process
    gone / unverifiable"), never raises out of the ticker."""
    import subprocess

    def _raise(*args, **kwargs):
        raise FileNotFoundError("ps: command not found")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert mod._ps_command_line(4242) == ""
