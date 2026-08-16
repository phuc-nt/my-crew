"""`my-crew agent step-replay <agent_id> <task_id> <step_id> [--attempt] [--model]` (v80 P2).

Re-runs one TEAM-TASK STEP from its frozen work-order — distinct from `agent replay`,
which replays a CHECKPOINT THREAD of the normal report pipeline. Replay here is a
RE-RUN, not a verbatim playback: persona/memory/model may have drifted since the
original attempt; the verbatim original messages live in the attempt's transcript.
Read-only against production data (the run happens in a throwaway sandbox data_dir)
and network-off by default (web hooks return a "REPLAY: network off" marker).
"""

from __future__ import annotations

import sys

from my_crew.entrypoints.mpm import _flag_value
from my_crew.entrypoints.mpm_manage_cmds import _load_agent
from my_crew.runtime.registry import load_registry
from my_crew.runtime.step_replay import replay_step

_USAGE = (
    "usage: my-crew agent step-replay <agent_id> <task_id> <step_id> "
    "[--attempt <attempt_id>] [--model <model>]\n"
    "  Chạy LẠI một bước team-task từ work-order đã đóng băng (re-run, không verbatim;\n"
    "  network off; không ghi gì vào store thật). So với `agent replay`: lệnh đó phát\n"
    "  lại checkpoint thread của pipeline báo cáo, lệnh này chạy lại một BƯỚC team-task."
)


def run_step_replay(args: list[str], *, replay=None) -> int:
    """Replay one team-step attempt. Returns 0 ok, 1 error, 2 bad invocation."""
    if len(args) < 3:
        print(_USAGE, file=sys.stderr)
        return 2
    agent_id, task_id, step_id = args[0], args[1], args[2]
    attempt_id = _flag_value(args, "--attempt")
    model = _flag_value(args, "--model")
    if "--attempt" in args and not attempt_id:
        print("error: --attempt requires an attempt_id.", file=sys.stderr)
        return 2
    if "--model" in args and not model:
        print("error: --model requires a model name.", file=sys.stderr)
        return 2
    replay = replay or replay_step

    try:
        known = {e.id for e in load_registry()}
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if agent_id not in known:
        print(f"error: unknown agent {agent_id!r} (not in registry.yaml).", file=sys.stderr)
        return 1
    loaded = _load_agent(agent_id)
    if loaded is None:
        return 1

    try:
        result = replay(
            loaded, loaded.settings, task_id=task_id, step_id=step_id,
            attempt_id=attempt_id, model=model,
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    order = result.get("work_order") or {}
    text = str(result.get("result_text") or "")
    head = text[:400] + ("…" if len(text) > 400 else "")
    print(f"step-replay {task_id}/{step_id} (attempt gốc: {order.get('attempt_id', '?')})")
    print(f"  runtime: {result.get('effective_kind')}  cost: {result.get('cost_usd')}")
    print(f"  diff vs artifact gốc: {result.get('diff_summary')}")
    print("  kết quả replay (đầu):")
    print(f"  {head or '(rỗng)'}")
    return 0
