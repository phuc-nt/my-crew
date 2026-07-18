"""B3 run replay / time-travel (v2 M3-P12) — re-run a thread from a saved checkpoint.

Replay-from-checkpoint is the ONLY mode this round (KISS): it resumes a thread from the
FROZEN stored state at a checkpoint — it does NOT re-fetch live Jira/GitHub. Re-execute
(re-fetch) and time-travel state edits are deferred future toggles, intentionally not built.

Replay adds NO new write path: it re-runs an EXISTING compiled graph whose deliver node
already routes every mutation through the Action Gateway (Lớp A/B + dedup). A replay that
reaches a write hits the SAME guard chain as the original run — no bypass, no new authority.

`build_graph` is injected (like `worker_resume`) so tests run on a tmp SQLite checkpoint
with no live data.
"""

from __future__ import annotations

from typing import Any

from my_crew.runtime.agent_paths import parse_thread_id

# Nodes that read ONLY checkpointed state (no closure-local fetch box): replaying from a
# checkpoint pending one of these is faithful. perceive/analyze/compose rebuild the fetch
# box on a fresh process, so a checkpoint pending THEM would run against an empty box
# (degenerate report or KeyError) — those are refused. `deliver`/`approval_gate` are the
# resume-safe nodes (the same set M2-P5 `worker_resume` resumes at). An empty `next`
# (terminal) checkpoint has nothing left to run and is also safe (replay is a no-op).
_REPLAY_SAFE_NODES = frozenset({"deliver", "approval_gate"})


def _thread_config(thread_id: str, checkpoint_id: str | None = None) -> dict[str, Any]:
    """Build the per-thread RunnableConfig, optionally pinned to a checkpoint."""
    configurable: dict[str, Any] = {"thread_id": thread_id}
    if checkpoint_id:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable}


def list_checkpoints(loaded, settings, thread_id: str, *, build_graph) -> list[dict[str, Any]]:
    """Return the checkpoint history for a thread (newest first), non-PII summary only.

    Each entry: checkpoint_id, step, source, next (pending nodes), created_at. The summary
    is structural (node/step) — it never includes report text or other PII, mirroring the
    P5 interrupt summary discipline.
    """
    _, kind, audience = parse_thread_id(thread_id)
    graph = build_graph(loaded, settings, kind, audience)
    history = graph.get_state_history(_thread_config(thread_id))
    out: list[dict[str, Any]] = []
    for snap in history:
        meta = snap.metadata or {}
        pending = tuple(snap.next or ())
        out.append(
            {
                "checkpoint_id": snap.config.get("configurable", {}).get("checkpoint_id"),
                "step": meta.get("step"),
                "source": meta.get("source"),
                "next": list(pending),
                "created_at": getattr(snap, "created_at", None),
                # Replayable when pending a state-only node (or terminal) — an earlier
                # checkpoint would re-fetch/KeyError on the un-checkpointed fetch box.
                "replayable": (not pending) or set(pending).issubset(_REPLAY_SAFE_NODES),
            }
        )
    return out


def replay_from_checkpoint(
    loaded, settings, thread_id: str, checkpoint_id: str, *, build_graph
) -> dict[str, Any]:
    """Resume a thread from a saved checkpoint using the frozen stored state (no re-fetch).

    Invokes with `input=None` + a checkpoint-pinned config, so LangGraph continues from the
    checkpoint's stored values rather than re-running the perceive/fetch nodes. Raises a
    clear error if the checkpoint_id is unknown for the thread.
    """
    if not checkpoint_id:
        raise ValueError("replay_from_checkpoint requires a checkpoint_id.")
    _, kind, audience = parse_thread_id(thread_id)
    graph = build_graph(loaded, settings, kind, audience)

    # Locate the target snapshot (clean error if the id is unknown for this thread).
    target = next(
        (
            snap
            for snap in graph.get_state_history(_thread_config(thread_id))
            if snap.config.get("configurable", {}).get("checkpoint_id") == checkpoint_id
        ),
        None,
    )
    if target is None:
        raise ValueError(
            f"checkpoint {checkpoint_id!r} not found for thread {thread_id!r}."
        )

    # Refuse a checkpoint pending a fetch-box node (perceive/analyze/compose): on a fresh
    # process the box is empty, so replaying there re-fetches live data or hits a KeyError.
    # Only checkpoints pending a state-only node (deliver/approval_gate) or terminal replay
    # faithfully. This also blocks a pre-perceive checkpoint from silently re-fetching.
    pending = tuple(target.next or ())
    if pending and not set(pending).issubset(_REPLAY_SAFE_NODES):
        raise ValueError(
            f"checkpoint {checkpoint_id!r} is pending {pending} — replay supports only "
            f"checkpoints at {sorted(_REPLAY_SAFE_NODES)} or terminal (the report's fetched "
            f"data is not checkpointed, so an earlier checkpoint would re-fetch live data). "
            f"Pick a later checkpoint from `mpm agent replay <id> <thread>`."
        )
    return graph.invoke(None, config=_thread_config(thread_id, checkpoint_id))
