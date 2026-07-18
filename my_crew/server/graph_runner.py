"""Default graph-build seam + terminal derivation for in-process runs (v2 M2-P6).

Keeps the profile/LLM wiring OUT of `run_manager` so the manager is testable with a
fake graph and zero profile deps. The default `build_graph` loads the agent's profile
at its per-agent data dir and builds the same graph the worker runs — so a triggered
run goes through the identical per-agent gateway (Lớp A/B + audit + budget + dedup).
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Terminal:
    """The terminal event pushed once at the end of every run.

    status ∈ {delivered, not_delivered, interrupted, error}. `thread_id`/`summary`
    are set for `interrupted` (so the operator knows to `mpm agent resume`); `message`
    is a short, PII-free string for `error`.
    """

    status: str
    thread_id: str | None = None
    summary: str | None = None
    message: str | None = None


def default_build_graph(agent_id: str, kind: str, audience: str, dry_run: bool):
    """Build the same per-agent graph the worker runs (real profile + gateway).

    Lazy imports keep `run_manager` importable without the heavy graph stack and keep
    graph-build network-free (the LLM key is only needed lazily at the compose node).
    """
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.worker import build_graph_for

    loaded = load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    settings = loaded.settings
    if dry_run:
        settings = replace(settings, dry_run=True)
    return build_graph_for(loaded, settings, kind, audience)


def terminal_for_delivery(last_delta: dict | None) -> Terminal:
    """Terminal for a graph that ran to completion (no interrupt).

    `delivered` true → delivered; false/absent → not_delivered. `last_delta` is the
    `deliver` node's state-delta (or None if the graph never reached deliver).
    """
    delivered = bool((last_delta or {}).get("delivered", False))
    return Terminal(status="delivered" if delivered else "not_delivered")


def terminal_for_interrupt(thread_id: str, interrupt_chunk: dict) -> Terminal:
    """Terminal for a graph paused at the Lớp B approval gate.

    Carries the thread_id (to resume via `mpm agent resume`) and the interrupt's
    non-PII summary (built by the P5 approval_gate, channel + kind only).
    """
    summary = None
    payload = interrupt_chunk.get("__interrupt__")
    if payload:
        value = getattr(payload[0], "value", None)
        if isinstance(value, dict):
            summary = value.get("summary")
    return Terminal(status="interrupted", thread_id=thread_id, summary=summary)
