"""`mpm agent run <id> --report <kind> [--audience ...] [--dry-run]`.

Runs ONE report for one agent by SPAWNING the P3 worker subprocess — the SAME argv
shape the coordinating service uses (`service._worker_argv`), so the one-off CLI run and
the scheduler stay in lock-step on the worker contract. Waits, collects the worker's exit
code + the last `runs.jsonl` line, prints the outcome. The spawn fn is injectable so tests
assert the exact argv with no real process.
"""

from __future__ import annotations

import sys

from my_crew.entrypoints.mpm import _flag_value
from my_crew.runtime.registry import load_registry
from my_crew.runtime.service import _real_spawn, _supervise, _worker_argv

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
    from my_crew.packs.registry import all_report_kinds

    # `inbox` is a generic run kind (M11 ask-agent poll); `team-step` (v12 M28a) is a
    # per-step team-task run; `team-tick` (v12 M28b) is the coordinator's own short poll;
    # `milestone-mirror` (v12 M29) is the admin agent's room→Telegram digest — none is a
    # pack report kind, so all four are handled by the worker before graph dispatch and
    # are always valid --report values.
    valid_kinds = all_report_kinds() | {"inbox", "team-step", "team-tick", "milestone-mirror"}
    if kind not in valid_kinds:
        print(
            f"error: --report must be one of {sorted(valid_kinds)}; got {kind!r}.",
            file=sys.stderr,
        )
        return 2
    # v12 M28a: a team-step invocation needs the (task, step, attempt) triple the P3
    # coordinator's reserve_step issued as its lease token; the worker rejects a
    # bare/malformed invocation as a clean no-op (no open step ⇒ nothing to run).
    task_id = _flag_value(args, "--task-id")
    step_id = _flag_value(args, "--step-id")
    attempt_id = _flag_value(args, "--attempt-id")
    if kind == "team-step" and not (task_id and step_id and attempt_id):
        print(
            "error: --report team-step requires --task-id --step-id --attempt-id",
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
    if kind == "team-step":
        argv += ["--task-id", task_id, "--step-id", step_id, "--attempt-id", attempt_id]
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
