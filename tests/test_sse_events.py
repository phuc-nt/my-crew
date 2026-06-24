"""M2-P6 Slice 3: summarize_node PII firewall + SSE event builders (pure, offline)."""

from __future__ import annotations

import json

from src.server.graph_runner import Terminal
from src.server.sse_events import node_event, summarize_node, terminal_event


def test_summarize_node_drops_pii():
    # Poisoned with the REAL field names the live analyze nodes emit (assignee names,
    # issue subjects/details) + profile data → only the count survives.
    delta = {
        "risks": [
            {"assignee": "Alice", "subject": "PROJ-12", "detail": "secret blocker text",
             "refs": ("PROJ-99",)},
            {"assignee": "Bob", "subject": "PROJ-13", "detail": "more secret"},
        ],
        "persona": "SECRET_PERSONA",
        "project": "SECRET_PROJECT",
        "memory": "SECRET_MEMORY",
    }
    out = summarize_node("analyze", delta)
    assert out == {"risk_count": 2}
    blob = json.dumps(out)
    for marker in ("PERSONA", "PROJECT", "MEMORY", "Alice", "Bob", "PROJ-12", "secret"):
        assert marker not in blob


def test_summarize_compose_only_cost():
    delta = {"cost_usd": 0.01, "report_text": "<h2>secret body</h2>"}
    out = summarize_node("compose_report", delta)
    assert out == {"cost_usd": 0.01}
    assert "secret body" not in json.dumps(out)


def test_summarize_deliver_bool_and_summary():
    out = summarize_node("deliver", {"delivered": True, "delivery_summary": "slack=executed"})
    assert out == {"delivered": True, "summary": "slack=executed"}


def test_summarize_perceive_and_unknown_drop_all():
    assert summarize_node("perceive", {"issues": ["x"], "persona": "X"}) == {}
    assert summarize_node("some_new_node", {"anything": "leak"}) == {}


def test_summarize_approval_gate_paused():
    assert summarize_node("approval_gate", {"approval_decision": "approve"}) == {"state": "paused"}


def test_node_event_payload_shape():
    payload = json.loads(node_event("analyze", {"risks": [{"x": 1}]}))
    assert payload == {"event": "node", "node": "analyze", "data": {"risk_count": 1}}


def test_terminal_event_interrupted_carries_thread_and_summary():
    t = Terminal(status="interrupted", thread_id="acme:daily:external", summary="→ Slack C1")
    payload = json.loads(terminal_event(t))
    assert payload["event"] == "terminal" and payload["status"] == "interrupted"
    assert payload["data"]["thread_id"] == "acme:daily:external"
    assert payload["data"]["summary"] == "→ Slack C1"


def test_terminal_event_error_carries_message_only():
    payload = json.loads(terminal_event(Terminal(status="error", message="boom")))
    assert payload["status"] == "error" and payload["data"] == {"message": "boom"}


def test_terminal_event_delivered_empty_data():
    payload = json.loads(terminal_event(Terminal(status="delivered")))
    assert payload["status"] == "delivered" and payload["data"] == {}
