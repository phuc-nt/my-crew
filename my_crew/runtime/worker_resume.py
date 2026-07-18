"""Worker `--resume` path (v2 M2-P5): resume a graph paused at a Lớp B interrupt.

    python -m my_crew.runtime.worker --agent-id <id> --resume \
        --thread <thread_id> --decision approve|reject

The fresh run left the graph PAUSED at the `approval_gate` node with its state
checkpoint-serialized at `thread_id`. This re-attaches to that SAME thread on the
agent's per-agent checkpointer and resumes it with `Command(resume=decision)`:
approve → the graph routes to `deliver` and posts LIVE (gateway already-approved
path); reject → the graph routes to `END`, nothing posted, the decision is audited.

Resume reads the agent's configured checkpointer (SqliteSaver by default, or a
PostgresSaver when opted in via P8). With the SQLite default this is same-machine
resume; durable cross-process/cross-machine resume is the Postgres opt-in (P8). The
thread_id encodes `<agent_id>:<kind>:<audience>` so the SAME graph structure is
rebuilt — a resume must reconstruct the node/edge shape the checkpoint was created with.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import Command

from my_crew.profile.loader import LoadedProfile
from my_crew.runtime.agent_paths import parse_thread_id

logger = logging.getLogger(__name__)

_DECISIONS = {"approve", "reject"}


def resume_report(
    loaded: LoadedProfile,
    settings: Any,
    thread_id: str,
    decision: str,
    *,
    build_graph,
) -> dict:
    """Rebuild the matching graph and resume the paused thread with the decision.

    `build_graph(loaded, settings, kind, audience)` returns the compiled graph (the
    worker injects `build_graph_for`, kept injectable so tests stay offline). Returns
    the resumed graph's final state dict.
    """
    _, kind, audience = parse_thread_id(thread_id)
    graph = build_graph(loaded, settings, kind, audience)
    return graph.invoke(
        Command(resume=decision), config={"configurable": {"thread_id": thread_id}}
    )


def run_resume(
    args: list[str],
    *,
    agent_id: str,
    loaded: LoadedProfile,
    settings: Any,
    data_dir,
    build_graph,
    flag_value,
    append_event,
    make_event,
) -> int:
    """Handle `worker --resume`: validate flags, resume, record the outcome.

    Returns 0 (delivered after approve), 1 (rejected / not delivered / error), or 2
    (bad invocation). The collaborators (flag_value/append_event/make_event/
    build_graph) are injected from `worker.py` to avoid a circular import and to keep
    the path offline-testable.
    """
    thread_id = flag_value(args, "--thread")
    decision = flag_value(args, "--decision")
    if not thread_id or decision not in _DECISIONS:
        print("usage: --resume --thread <thread_id> --decision approve|reject")
        return 2

    # The thread id must belong to THIS agent (no resuming another agent's thread).
    try:
        thread_agent, kind, audience = parse_thread_id(thread_id)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2
    if thread_agent != agent_id:
        print(f"error: thread {thread_id!r} is not agent {agent_id!r}'s thread.")
        return 2

    try:
        result = resume_report(loaded, settings, thread_id, decision, build_graph=build_graph)
    except Exception as exc:  # noqa: BLE001 — record, never crash the worker
        logger.exception("resume %s/%s failed", agent_id, kind)
        append_event(data_dir, make_event(agent_id, kind, audience, "error", None, False))
        print(f"error: {exc}")
        return 1

    if decision == "reject":
        append_event(data_dir, make_event(agent_id, kind, audience, "rejected", None, False))
        logger.info("worker %s %s/%s: REJECTED — nothing posted", agent_id, kind, audience)
        return 1

    delivered = bool(result.get("delivered", False))
    cost = result.get("cost_usd")
    status = "delivered" if delivered else "not_delivered"
    append_event(data_dir, make_event(agent_id, kind, audience, status, cost, delivered))
    logger.info("worker %s %s/%s resume: delivered=%s %s",
                agent_id, kind, audience, delivered, result.get("delivery_summary", ""))
    return 0 if delivered else 1
