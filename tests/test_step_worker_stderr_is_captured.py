"""A dispatched step worker's stderr must be kept, not discarded.

The step worker is a detached child process, so everything about HOW a step ran — which
runtime tier it resolved to, whether its tool loop hit the recursion cap and degraded to an
empty result, why a provider call was skipped — is logged inside that child. Sending its
stderr to DEVNULL meant the service log legitimately contained none of it, and diagnosing a
bad step required reproducing it by hand outside the daemon.

Real cost: an empty-result step (task 3e4a8d64ea20) took an entire investigation to explain
because the one process that knew the answer had its output thrown away.
"""

from __future__ import annotations

import subprocess

from my_crew.runtime.team_tick_runner import _make_spawn_step, _step_worker_log_path


class _Step:
    assigned_to = "researcher"
    step_id = "step1"


class _Task:
    id = "t1"


def _spawn_capturing(monkeypatch):
    """Run the real spawn with Popen stubbed, returning the kwargs it was called with."""
    seen: dict = {}

    class _Proc:
        pid = 4321

    def _fake_popen(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return _Proc()

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    pid = _make_spawn_step()(_Task(), _Step(), "attempt-1")
    seen["pid"] = pid
    return seen


def test_stderr_is_not_discarded(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "my_crew.runtime.team_tick_runner.team_tasks_root", lambda: tmp_path
    )
    seen = _spawn_capturing(monkeypatch)
    assert seen["kwargs"]["stderr"] is not subprocess.DEVNULL


def test_the_log_file_is_created_under_the_data_dir(monkeypatch, tmp_path):
    """The parent directory must be created eagerly — `open(..., 'a')` does not make it,
    so a missing `logs/` would send every spawn down the OSError fallback silently."""
    monkeypatch.setattr(
        "my_crew.runtime.team_tick_runner.team_tasks_root", lambda: tmp_path
    )
    path = _step_worker_log_path()
    assert path.parent.is_dir()
    assert path.parent == tmp_path / "logs"


def test_a_broken_log_path_still_dispatches_the_step(monkeypatch, tmp_path):
    """Logging is diagnostics, not the job. If the sink cannot be opened, the step must
    still be spawned (stderr discarded) rather than the tick refusing to dispatch work."""
    monkeypatch.setattr(
        "my_crew.runtime.team_tick_runner._step_worker_log_path",
        lambda: (_ for _ in ()).throw(OSError("read-only fs")),
    )
    seen = _spawn_capturing(monkeypatch)
    assert seen["pid"] == 4321
    assert seen["kwargs"]["stderr"] is subprocess.DEVNULL


def test_the_parent_closes_its_copy_of_the_fd(monkeypatch, tmp_path):
    """The ticker is long-lived and dispatches many steps; the child holds its own dup, so
    a parent copy left open would leak one descriptor per step until exhaustion."""
    monkeypatch.setattr(
        "my_crew.runtime.team_tick_runner.team_tasks_root", lambda: tmp_path
    )
    seen = _spawn_capturing(monkeypatch)
    assert seen["kwargs"]["stderr"].closed


def test_the_spawn_still_carries_the_step_identity(monkeypatch, tmp_path):
    """Guard against the logging change quietly altering the worker invocation itself."""
    monkeypatch.setattr(
        "my_crew.runtime.team_tick_runner.team_tasks_root", lambda: tmp_path
    )
    argv = _spawn_capturing(monkeypatch)["argv"]
    assert "--task-id" in argv and "t1" in argv
    assert "--step-id" in argv and "step1" in argv
    assert "researcher" in argv
