"""SSE event projection + the PII firewall for streamed runs (v2 M2-P6).

`summarize_node` is the ONE security-critical function here: it projects a raw graph
node delta down to an ALLOWLIST of non-PII fields. Anything not on the allowlist is
DROPPED — so persona / project / memory / per-assignee data can never reach an SSE
client even if a future node leaks it into its state-delta. (Same red line as the P5
approval-gate summary.) Pure functions, no FastAPI import — unit-tested directly.
"""

from __future__ import annotations

import json

from src.server.graph_runner import Terminal


def summarize_node(node: str, delta: dict) -> dict:
    """Project a node's raw state-delta to its non-PII allowlist (drop everything else).

    Unknown nodes → {} (drop all): a safe default if the graph grows a node.
    """
    if node == "analyze":
        return {"risk_count": len(delta.get("risks", []))}
    if node == "compose_report":
        return {"cost_usd": delta.get("cost_usd")}
    if node == "approval_gate":
        return {"state": "paused"}
    if node == "deliver":
        return {
            "delivered": bool(delta.get("delivered", False)),
            "summary": str(delta.get("delivery_summary", "")),
        }
    # perceive + any unknown node carry nothing (counts are not cheaply available
    # and are not worth leaking a delta for).
    return {}


def node_event(node: str, delta: dict) -> str:
    """JSON payload (the SSE `data` value) for one node update, firewall-projected."""
    return json.dumps(
        {"event": "node", "node": node, "data": summarize_node(node, delta)},
        ensure_ascii=False,
    )


def terminal_event(terminal: Terminal) -> str:
    """JSON payload (the SSE `data` value) for the terminal event."""
    data: dict = {}
    if terminal.status == "interrupted":
        data = {"thread_id": terminal.thread_id, "summary": terminal.summary}
    elif terminal.status == "error":
        data = {"message": terminal.message}
    return json.dumps(
        {"event": "terminal", "status": terminal.status, "data": data}, ensure_ascii=False
    )
