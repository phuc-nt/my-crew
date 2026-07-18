"""`mpm agent replay <id> <thread> [--checkpoint <id>]` (v2 M3-P12 B3).

Read-only sibling of `mpm agent resume`. With no `--checkpoint`, LISTS the checkpoint
history for a thread so the operator can pick one. With `--checkpoint <id>`, replays the
thread from that saved checkpoint using the FROZEN stored state (no re-fetch of live
Jira/GitHub — replay-from-checkpoint, the KISS default; re-fetch is deferred).

Runs IN-PROCESS (replay is read-mostly, not a delivery spawn). The graph is built once via
`build_graph_for`, opening the agent's checkpointer a single time. Replay adds no new write
path: a replay reaching a write hits the SAME Action-Gateway chain as the original run.
"""

from __future__ import annotations

import sys

from my_crew.entrypoints.mpm import _flag_value
from my_crew.entrypoints.mpm_manage_cmds import _load_agent
from my_crew.runtime.registry import load_registry
from my_crew.runtime.replay import list_checkpoints, replay_from_checkpoint


def _default_build_graph(loaded, settings, kind, audience):
    from my_crew.runtime.worker import build_graph_for

    return build_graph_for(loaded, settings, kind, audience)


def run_replay(args: list[str], *, build_graph=None) -> int:
    """List or replay checkpoints for a thread. Returns 0 ok, 1 error, 2 bad invocation."""
    if len(args) < 2:
        print(
            "usage: mpm agent replay <id> <thread_id> [--checkpoint <checkpoint_id>]",
            file=sys.stderr,
        )
        return 2
    agent_id, thread_id = args[0], args[1]
    checkpoint_id = _flag_value(args, "--checkpoint")
    # `--checkpoint` present but with no value would silently fall back to listing; refuse.
    if "--checkpoint" in args and not checkpoint_id:
        print("error: --checkpoint requires a checkpoint_id.", file=sys.stderr)
        return 2
    build_graph = build_graph or _default_build_graph

    # Existence pre-check: a typo'd id is a clean "unknown agent".
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
    settings = loaded.settings

    try:
        if checkpoint_id is None:
            return _print_history(loaded, settings, thread_id, build_graph)
        return _do_replay(loaded, settings, thread_id, checkpoint_id, build_graph)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _print_history(loaded, settings, thread_id, build_graph) -> int:
    entries = list_checkpoints(loaded, settings, thread_id, build_graph=build_graph)
    if not entries:
        print(f"{thread_id}: no checkpoints found.")
        return 0
    print(f"checkpoints for {thread_id} (newest first):")
    for e in entries:
        nxt = ",".join(e["next"]) or "-"
        mark = "replayable" if e["replayable"] else "needs-earlier-data"
        print(
            f"  {e['checkpoint_id']}  step={e['step']} source={e['source']} "
            f"next={nxt} [{mark}] at={e['created_at']}"
        )
    print(
        "replay a [replayable] one with: "
        "mpm agent replay <id> <thread> --checkpoint <checkpoint_id>"
    )
    return 0


def _do_replay(loaded, settings, thread_id, checkpoint_id, build_graph) -> int:
    result = replay_from_checkpoint(
        loaded, settings, thread_id, checkpoint_id, build_graph=build_graph
    )
    delivered = result.get("delivered") if isinstance(result, dict) else None
    summary = result.get("delivery_summary") if isinstance(result, dict) else None
    line = f"{thread_id} replay from {checkpoint_id}: delivered={delivered} {summary or ''}"
    print(line.rstrip())
    return 0
