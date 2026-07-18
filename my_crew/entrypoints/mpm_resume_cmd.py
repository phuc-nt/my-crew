"""`mpm agent resume <id> <thread_id> --decision approve|reject` (v2 M2-P5).

Resumes a graph paused at a Lớp B interrupt by SPAWNING the worker `--resume` path
(the same subprocess contract `mpm agent run` uses, via `service._supervise`). Approve
posts the external report LIVE; reject stops it clean. Waits, collects the worker exit
code + the last `runs.jsonl` line, prints the outcome. The spawn fn is injectable so
tests assert the exact argv with no real process.
"""

from __future__ import annotations

import sys

from my_crew.entrypoints.mpm import _flag_value
from my_crew.runtime.registry import load_registry
from my_crew.runtime.service import _real_spawn, _supervise

_DECISIONS = {"approve", "reject"}
_DEFAULT_TIMEOUT = 600


def _resume_argv(agent_id: str, thread_id: str, decision: str) -> list[str]:
    return [
        sys.executable, "-m", "my_crew.runtime.worker",
        "--agent-id", agent_id, "--resume",
        "--thread", thread_id, "--decision", decision,
    ]


def run_resume(args: list[str], *, spawn=None, timeout: int = _DEFAULT_TIMEOUT) -> int:
    """Spawn the worker resume for one paused thread; print the outcome.

    Returns 0 (delivered after approve), 1 (rejected / non-zero / timeout / unknown
    agent), or 2 (bad invocation).
    """
    if len(args) < 2:
        print(
            "usage: mpm agent resume <id> <thread_id> --decision approve|reject",
            file=sys.stderr,
        )
        return 2
    agent_id, thread_id = args[0], args[1]
    decision = _flag_value(args, "--decision")
    if decision not in _DECISIONS:
        print("error: --decision must be approve|reject.", file=sys.stderr)
        return 2

    # Existence pre-check: a typo'd id is a clean "unknown agent", not a worker exit 2.
    try:
        known = {e.id for e in load_registry()}
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if agent_id not in known:
        print(f"error: unknown agent {agent_id!r} (not in registry.yaml).", file=sys.stderr)
        return 1

    argv = _resume_argv(agent_id, thread_id, decision)
    outcome = _supervise(spawn or _real_spawn, argv, timeout=timeout)
    if outcome["status"] == "timeout":
        print(f"{agent_id} resume: TIMEOUT after {timeout}s (worker killed)")
        return 1
    detail = outcome.get("detail") or {}
    print(
        f"{agent_id} resume {decision} ({thread_id}): exit={outcome['exit_code']} "
        f"delivered={detail.get('delivered')} status={detail.get('status')}"
    )
    return 0 if outcome["exit_code"] == 0 else 1
