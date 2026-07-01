"""`mpm agent run <id> --report <kind> [--audience ...] [--dry-run]`.

Runs ONE report for one agent by SPAWNING the P3 worker subprocess — the SAME argv
shape the coordinating service uses (`service._worker_argv`), so the one-off CLI run and
the scheduler stay in lock-step on the worker contract. Waits, collects the worker's exit
code + the last `runs.jsonl` line, prints the outcome. The spawn fn is injectable so tests
assert the exact argv with no real process.
"""

from __future__ import annotations

import sys

from src.entrypoints.mpm import _flag_value
from src.runtime.registry import load_registry
from src.runtime.service import _real_spawn, _supervise, _worker_argv

_DEFAULT_TIMEOUT = 600


def run_agent(args: list[str], *, spawn=None, timeout: int = _DEFAULT_TIMEOUT) -> int:
    """Spawn the worker for one agent + report kind; print the outcome.

    Returns 0 (worker delivered), 1 (worker non-zero / timeout / unknown agent), or 2
    (bad invocation — missing id, invalid kind).
    """
    if not args:
        print(
            "usage: mpm agent run <id> --report <kind> [--audience ...] [--dry-run]",
            file=sys.stderr,
        )
        return 2
    agent_id = args[0]
    kind = _flag_value(args, "--report") or "daily"
    # Validate against the union of all packs' kinds (pack-aware, not a hardcoded PM
    # set) so a domain pack's kind (e.g. HR `headcount`) is accepted. The worker still
    # enforces that the agent's own pack serves the kind.
    from src.packs.registry import all_report_kinds

    valid_kinds = all_report_kinds()
    if kind not in valid_kinds:
        print(
            f"error: --report must be one of {sorted(valid_kinds)}; got {kind!r}.",
            file=sys.stderr,
        )
        return 2
    audience = "external" if _flag_value(args, "--audience") == "external" else "internal"

    # Existence pre-check: a typo'd id is a clean "unknown agent", not a deep worker exit 2.
    try:
        known = {e.id for e in load_registry()}
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if agent_id not in known:
        print(f"error: unknown agent {agent_id!r} (not in registry.yaml).", file=sys.stderr)
        return 1

    argv = _worker_argv(agent_id, kind, audience)
    if "--dry-run" in args:
        argv.append("--dry-run")

    outcome = _supervise(spawn or _real_spawn, argv, timeout=timeout)
    if outcome["status"] == "timeout":
        print(f"{agent_id} {kind}: TIMEOUT after {timeout}s (worker killed)")
        return 1
    detail = outcome.get("detail") or {}
    print(
        f"{agent_id} {kind}/{audience}: exit={outcome['exit_code']} "
        f"delivered={detail.get('delivered')} status={detail.get('status')} "
        f"cost={detail.get('cost_usd')}"
    )
    return 0 if outcome["exit_code"] == 0 else 1
