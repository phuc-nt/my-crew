"""v6 M14b: CEO chat-ops web endpoint. Offline (engine + agent lookup stubbed).

Load-bearing:
- POST /api/ops/chat drives the SAME handle_ops_message engine against the SAME
  per-operator conversation store — the conversation_key is the admin agent's
  ops_operator_id, so web + Telegram share one draft.
- /chat/available reports whether an admin ops agent exists (never raises).
- No admin ops agent ⇒ 400 with a Vietnamese hint (nothing to administer through).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.server import routes_ops_chat
from src.server.app import create_app


def _client():
    return TestClient(create_app())


class _Loaded:
    class settings:
        data_dir = "/tmp/store-is-stubbed"


def test_chat_available_true_when_admin_ops_agent_exists(monkeypatch):
    monkeypatch.setattr(routes_ops_chat, "_find_ops_agent", lambda: ("admin", "555", _Loaded))
    r = _client().get("/api/ops/chat/available")
    assert r.status_code == 200 and r.json() == {"available": True, "agent_id": "admin"}


def test_chat_available_false_when_none(monkeypatch):
    from fastapi import HTTPException

    def _boom():
        raise HTTPException(status_code=400, detail="Chưa có agent quản trị")

    monkeypatch.setattr(routes_ops_chat, "_find_ops_agent", _boom)
    r = _client().get("/api/ops/chat/available")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False and "Chưa có agent" in body["reason"]


def test_post_chat_drives_engine_with_operator_conversation_key(monkeypatch):
    seen = {}

    monkeypatch.setattr(routes_ops_chat, "_find_ops_agent", lambda: ("admin", "555", _Loaded))
    monkeypatch.setattr("src.agent.ops_conversation_store.OpsConversationStore",
                        lambda path: type("S", (), {"close": lambda self: None})())
    monkeypatch.setattr("src.llm.client.LlmClient", lambda settings: object())

    def fake_handle(*, message, conversation_key, store, llm, now):
        seen.update(message=message, key=conversation_key)
        return "Đội hiện có 3 agent", 0.0

    monkeypatch.setattr("src.agent.ops_chat.handle_ops_message", fake_handle)

    r = _client().post("/api/ops/chat", json={"message": "đội mình sao rồi"})
    assert r.status_code == 200
    assert r.json()["reply"] == "Đội hiện có 3 agent"
    assert seen["message"] == "đội mình sao rồi"
    assert seen["key"] == "555"  # conversation_key is the operator id (shared with Telegram)


def test_post_chat_empty_message_is_400():
    r = _client().post("/api/ops/chat", json={"message": "   "})
    assert r.status_code == 400


def test_find_ops_agent_picks_first_deterministically_and_warns_on_multiple(monkeypatch, caplog):
    """Two admin agents sharing an operator id ⇒ pick first-in-registry + loud warn
    (review MEDIUM: cross-surface drafts would otherwise diverge silently)."""
    monkeypatch.setattr(
        routes_ops_chat, "read_all_agent_states",
        lambda: [{"agent_id": "admin-a"}, {"agent_id": "admin-b"}],
    )

    def _fake_require(agent_id):
        tg = type("T", (), {"ops_operator_id": "555"})()
        return type("L", (), {"domain": "admin", "config": type("C", (), {"telegram": tg})()})()

    monkeypatch.setattr("src.server.ops_helpers.require_agent", _fake_require)
    import logging

    with caplog.at_level(logging.WARNING):
        agent_id, operator, _loaded = routes_ops_chat._find_ops_agent()
    assert agent_id == "admin-a" and operator == "555"  # deterministic: first in registry
    assert any("multiple admin ops agents" in r.message for r in caplog.records)


def test_find_ops_agent_400_when_no_admin_ops(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(routes_ops_chat, "read_all_agent_states", lambda: [{"agent_id": "pm"}])
    _pm = type("L", (), {"domain": "pm", "config": type("C", (), {"telegram": None})()})()
    monkeypatch.setattr("src.server.ops_helpers.require_agent", lambda aid: _pm)
    import pytest

    with pytest.raises(HTTPException) as exc:
        routes_ops_chat._find_ops_agent()
    assert exc.value.status_code == 400


def test_post_chat_empty_engine_reply_becomes_hint(monkeypatch):
    monkeypatch.setattr(routes_ops_chat, "_find_ops_agent", lambda: ("admin", "555", _Loaded))
    monkeypatch.setattr("src.agent.ops_conversation_store.OpsConversationStore",
                        lambda path: type("S", (), {"close": lambda self: None})())
    monkeypatch.setattr("src.llm.client.LlmClient", lambda settings: object())
    monkeypatch.setattr("src.agent.ops_chat.handle_ops_message",
                        lambda **k: ("", None))  # engine says "this was a question"

    r = _client().post("/api/ops/chat", json={"message": "thời tiết hôm nay"})
    assert r.status_code == 200 and "quản lý đội" in r.json()["reply"]


def test_ops_chat_commands_listing_is_descriptions_only(monkeypatch, tmp_path):
    """v32 discoverability: the catalog listing exposes id/description/readonly and
    NOTHING else (no slots internals, no handlers)."""
    from fastapi.testclient import TestClient

    from src.server.app import create_app

    r = TestClient(create_app()).get("/api/ops/chat/commands")
    assert r.status_code == 200
    commands = r.json()["commands"]
    ids = {c["id"] for c in commands}
    assert {"create_agent", "get_status", "company_activity"} <= ids
    assert all(set(c) == {"id", "description", "readonly"} for c in commands)
