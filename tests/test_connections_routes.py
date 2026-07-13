"""v33 P1: Connections screen routes — presence-only reads, whitelisted writes, honest restart.

Load-bearing:
- No secret VALUE ever appears in any response payload (presence bools only).
- Writes go through merge_env + SETUP_WRITABLE_KEYS: unknown key → 400, nothing written.
- needs_restart flips after a successful write; restart endpoint reports managed=False
  honestly when launchd does not run the service.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.server import routes_connections


_FAKE_CHECKS = {
    "checks": [
        {"id": "openrouter", "label": "OpenRouter (LLM)", "ok": True,
         "detail": "OPENROUTER_API_KEY ✓", "hint": "set it"},
        {"id": "atlassian", "label": "Atlassian", "ok": False,
         "detail": "ATLASSIAN_API_TOKEN ✗", "hint": "Set the 3 ATLASSIAN_* vars in .env"},
        {"id": "jira_mcp", "label": "Jira MCP build", "ok": True, "detail": "/x", "hint": ""},
        {"id": "confluence_mcp", "label": "Confluence MCP build", "ok": True,
         "detail": "/y", "hint": ""},
        {"id": "slack", "label": "Slack", "ok": True, "detail": "đã xác thực", "hint": ""},
        {"id": "slack_mcp", "label": "Slack MCP build", "ok": True, "detail": "/z", "hint": ""},
        {"id": "websearch_key", "label": "Web search key", "ok": True,
         "detail": "no agent opts in", "hint": ""},
        {"id": "github", "label": "GitHub", "ok": True, "detail": "exit 0", "hint": ""},
        {"id": "gws", "label": "gws CLI", "ok": False, "detail": "not on PATH",
         "hint": "Install the gws CLI"},
    ],
    "checked_at": 0.0,
}

_SECRET = "sk-or-v1-super"  # value that must NEVER round-trip into a response


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(f"OPENROUTER_API_KEY={_SECRET}\n", encoding="utf-8")
    monkeypatch.setattr("src.server.env_writer._ENV_PATH", env)
    monkeypatch.setattr(routes_connections, "integration_checks", lambda: _FAKE_CHECKS)
    monkeypatch.setattr(routes_connections, "_needs_restart", False)
    return env


def _client():
    from src.server.app import create_app

    return TestClient(create_app())


def test_cards_presence_only_never_a_value(env_file):
    r = _client().get("/api/connections")
    assert r.status_code == 200
    body = r.json()
    assert _SECRET not in r.text  # the secret value never leaves the server
    by_id = {c["id"]: c for c in body["cards"]}
    openrouter_keys = {k["name"]: k["set"] for k in by_id["openrouter"]["keys"]}
    assert openrouter_keys["OPENROUTER_API_KEY"] is True
    assert openrouter_keys["OPENROUTER_MODEL"] is False
    assert body["needs_restart"] is False


def test_card_status_aggregates_all_checks(env_file):
    by_id = {c["id"]: c for c in _client().get("/api/connections").json()["cards"]}
    # atlassian card = atlassian ✗ + both MCP builds ✓ → not ok, hint from the failing check
    assert by_id["atlassian"]["ok"] is False
    assert "ATLASSIAN" in by_id["atlassian"]["hint"]
    assert by_id["slack"]["ok"] is True
    # cards without checks: telegram (note only) and nokey (static ok)
    assert by_id["nokey"]["ok"] is True
    assert by_id["telegram"]["note"]


def test_put_keys_writes_and_flips_needs_restart(env_file):
    client = _client()
    r = client.put("/api/connections/keys", json={"updates": {"TAVILY_API_KEY": "tvly-1"}})
    assert r.status_code == 200
    assert r.json()["needs_restart"] is True
    assert "TAVILY_API_KEY=tvly-1" in env_file.read_text(encoding="utf-8")
    assert _client().get("/api/connections").json()["needs_restart"] is True


def test_put_unknown_key_is_400_and_writes_nothing(env_file):
    before = env_file.read_text(encoding="utf-8")
    r = _client().put(
        "/api/connections/keys",
        json={"updates": {"PATH": "/evil", "TAVILY_API_KEY": "tvly-1"}},
    )
    assert r.status_code == 400
    assert env_file.read_text(encoding="utf-8") == before  # all-or-nothing


def test_put_newline_in_value_is_400_nothing_written(env_file):
    """A newline in a VALUE would append a second KEY=... line — a whitelist bypass
    (e.g. smuggling WEB_AUTH_PASSWORD_HASH). Must refuse all-or-nothing."""
    before = env_file.read_text(encoding="utf-8")
    r = _client().put(
        "/api/connections/keys",
        json={"updates": {"OPENROUTER_MODEL": "x\nWEB_AUTH_PASSWORD_HASH=evil"}},
    )
    assert r.status_code == 400
    assert env_file.read_text(encoding="utf-8") == before
    assert "WEB_AUTH_PASSWORD_HASH" not in env_file.read_text(encoding="utf-8")


def test_put_blank_only_is_400(env_file):
    r = _client().put("/api/connections/keys", json={"updates": {"TAVILY_API_KEY": "  "}})
    assert r.status_code == 400


def test_restart_honest_when_not_launchd_managed(env_file, monkeypatch):
    monkeypatch.setattr("src.server.routes_setup._restart_web_service", lambda: False)
    r = _client().post("/api/connections/restart")
    assert r.status_code == 200
    body = r.json()
    assert body["managed"] is False
    assert "thủ công" in body["message"]


def test_restart_reports_managed_when_launchd_accepts(env_file, monkeypatch):
    monkeypatch.setattr("src.server.routes_setup._restart_web_service", lambda: True)
    body = _client().post("/api/connections/restart").json()
    assert body["managed"] is True


def test_catalog_keys_are_all_wizard_writable():
    from src.server.env_writer import SETUP_WRITABLE_KEYS

    for card in routes_connections._CATALOG:
        for key in card["keys"]:
            assert key in SETUP_WRITABLE_KEYS
