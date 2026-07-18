"""`my-crew serve` — web dashboard + coordinator in the foreground, one supervisor.

The cross-platform run path (docker compose, systemd, a plain terminal): spawns the
same two module entrypoints launchd runs (`my_crew.server.app`, `my_crew.runtime.service`)
as child processes, forwards SIGTERM/SIGINT to them, and exits when any child dies so
the OUTER supervisor (compose `restart:`, systemd `Restart=`) decides what happens
next — this process never restarts children itself. launchd stays the richer macOS
opt-in (`deploy/install.sh`).
"""

from __future__ import annotations

import signal
import subprocess
import sys
import time

_CHILD_MODULES = {
    "web": "my_crew.server.app",
    "scheduler": "my_crew.runtime.service",
}


def _spawn(name: str) -> subprocess.Popen:
    # Children inherit stdout/stderr: `serve` is a foreground command, logs belong on
    # the terminal (or the container log driver) — no repo-local log files here.
    return subprocess.Popen([sys.executable, "-m", _CHILD_MODULES[name]])


def _poll_exited(procs: dict[str, subprocess.Popen]) -> tuple[str, int] | None:
    """First (name, returncode) among exited children, or None while all run."""
    for name, proc in procs.items():
        rc = proc.poll()
        if rc is not None:
            return name, rc
    return None


def _terminate_all(procs: dict[str, subprocess.Popen], *, grace_s: float = 10.0) -> None:
    for proc in procs.values():
        if proc.poll() is None:
            proc.terminate()
    deadline = time.monotonic() + grace_s
    for proc in procs.values():
        remaining = max(0.1, deadline - time.monotonic())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def run_serve(args: list[str]) -> int:
    """Blocking. `--web-only` / `--scheduler-only` narrow to one child."""
    web_only = "--web-only" in args
    scheduler_only = "--scheduler-only" in args
    if web_only and scheduler_only:
        print("error: --web-only and --scheduler-only are mutually exclusive.", file=sys.stderr)
        return 2

    names = [
        n
        for n in _CHILD_MODULES
        if not (web_only and n != "web") and not (scheduler_only and n != "scheduler")
    ]
    procs = {name: _spawn(name) for name in names}
    print(f"my-crew serve: running {', '.join(procs)} (Ctrl-C to stop)", flush=True)

    stop_requested = False

    def _on_signal(signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True
        for proc in procs.values():
            if proc.poll() is None:
                proc.terminate()

    previous = {s: signal.signal(s, _on_signal) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        while True:
            exited = _poll_exited(procs)
            if exited is None:
                time.sleep(0.5)
                continue
            name, rc = exited
            if stop_requested:
                _terminate_all(procs)
                return 0
            # A child died on its own: bring the rest down and surface the failure —
            # the outer supervisor owns the restart decision.
            print(f"my-crew serve: {name} exited rc={rc} — stopping.", file=sys.stderr)
            _terminate_all(procs)
            return rc if rc != 0 else 1
    except KeyboardInterrupt:  # SIGINT raced the handler swap — same graceful path
        _terminate_all(procs)
        return 0
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
