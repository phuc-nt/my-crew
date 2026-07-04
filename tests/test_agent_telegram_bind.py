"""v7 M18a: bind a Telegram bot to an agent from the web (Agent Studio). Offline.

Load-bearing:
- The token is validated via getMe BEFORE persisting (a bad token → 400, no write).
- The token key is `<AGENT>_TELEGRAM_BOT_TOKEN` (whitelist pattern); env_writer accepts it
  only with the telegram flag.
- After binding, the token is override-loaded so it's live WITHOUT a restart (resolve reads
  os.environ per call).
- The `telegram:` block is added to profile.yaml (validated on save).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.server import routes_agent_knowledge


def _client():
    from src.server.app import create_app

    return TestClient(create_app())


@pytest.fixture
def agent_env(tmp_path, monkeypatch):
    """A throwaway .env + a stub profile so binding never touches the real repo."""
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_API_KEY=x\n", encoding="utf-8")
    monkeypatch.setattr("src.server.env_writer._ENV_PATH", env)
    monkeypatch.setattr("src.server.routes_agent_knowledge.REPO_ROOT", tmp_path, raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)  # don't reload real .env
    saved = {}
    monkeypatch.setattr("src.server.profile_editor.read_profile_files",
                        lambda aid: {"profile": "name: acme\ndomain: pm\n"})

    def _save(aid, text):
        # Run the REAL profile validation the editor runs (build_telegram etc.), so a block
        # that would fail load (e.g. empty chat_ids) fails HERE — no phantom pass (review M1).
        import yaml as _yaml

        from src.config.config_builders import build_reporting_config_from_dict
        from src.profile.loader_mapping import build_reporting_dict

        build_reporting_config_from_dict(build_reporting_dict(_yaml.safe_load(text)))
        saved.update(agent=aid, text=text)

    monkeypatch.setattr("src.server.profile_editor.save_profile_yaml", _save)
    return {"env": env, "saved": saved}


def test_token_env_name_pattern():
    assert routes_agent_knowledge._token_env_name("acme-pm") == "ACME_PM_TELEGRAM_BOT_TOKEN"
    assert routes_agent_knowledge._token_env_name("hr") == "HR_TELEGRAM_BOT_TOKEN"


def test_bind_validates_token_and_persists(agent_env, monkeypatch):
    monkeypatch.setattr("src.actions.telegram_write.api_call",
                        lambda token, method, payload=None: {"username": "acme_bot"})
    r = _client().post("/api/agents/acme/telegram",
                       json={"token": "123:ABC", "chat_ids": ["555"]})
    assert r.status_code == 200
    body = r.json()
    assert body["bot_username"] == "acme_bot" and body["env_name"] == "ACME_TELEGRAM_BOT_TOKEN"
    # token written under the whitelisted per-agent key
    assert "ACME_TELEGRAM_BOT_TOKEN=123:ABC" in agent_env["env"].read_text(encoding="utf-8")
    # telegram block added to the profile with the chat id
    assert "telegram" in agent_env["saved"]["text"] and "555" in agent_env["saved"]["text"]
    assert "ACME_TELEGRAM_BOT_TOKEN" in agent_env["saved"]["text"]


def test_rebind_without_chatids_keeps_existing(agent_env, monkeypatch):
    """Re-binding (e.g. rotating the token) with no chat_ids must NOT wipe the chat_ids the
    operator set on a previous bind — the block is merged, not replaced."""
    monkeypatch.setattr("src.server.profile_editor.read_profile_files",
                        lambda aid: {"profile": "name: acme\ndomain: pm\n"
                                     "telegram:\n  bot_token_env: OLD\n  chat_ids:\n  - '999'\n"
                                     "  poll_minutes: 5\n"})
    monkeypatch.setattr("src.actions.telegram_write.api_call",
                        lambda token, method, payload=None: {"username": "acme_bot"})
    # re-bind WITH a chat id (required now); existing extra chat_ids/poll_minutes preserved
    _client().post("/api/agents/acme/telegram", json={"token": "123:ABC", "chat_ids": ["999"]})
    saved = agent_env["saved"]["text"]
    assert "999" in saved  # existing chat id preserved
    assert "poll_minutes: 5" in saved  # existing cadence preserved
    assert "ACME_TELEGRAM_BOT_TOKEN" in saved  # token env updated to the new name


def test_bind_rejects_bad_token(agent_env, monkeypatch):
    def _fail(token, method, payload=None):
        raise RuntimeError("telegram API getMe failed: 401 Unauthorized")

    monkeypatch.setattr("src.actions.telegram_write.api_call", _fail)
    r = _client().post("/api/agents/acme/telegram", json={"token": "bad", "chat_ids": ["555"]})
    assert r.status_code == 400 and "không hợp lệ" in r.json()["detail"]
    # nothing written on a bad token
    assert "TELEGRAM_BOT_TOKEN" not in agent_env["env"].read_text(encoding="utf-8")


def test_bind_rejects_bad_agent_id(agent_env):
    assert _client().post("/api/agents/BADID/telegram",
                          json={"token": "x"}).status_code == 400


def test_bind_empty_token_400(agent_env):
    assert _client().post("/api/agents/acme/telegram",
                          json={"token": "  "}).status_code == 400


def test_bind_without_chat_id_400_before_any_write(agent_env, monkeypatch):
    """review C1: binding with no chat id must 400 BEFORE writing anything — otherwise the
    token lands in .env but the profile save fails (builder rejects empty chat_ids), leaving
    a partial write. getMe must not even be called."""
    called = {"getMe": False}

    def _guard_getme(token, method, payload=None):
        called["getMe"] = True
        return {"username": "x"}

    monkeypatch.setattr("src.actions.telegram_write.api_call", _guard_getme)
    r = _client().post("/api/agents/acme/telegram", json={"token": "123:ABC"})  # no chat_ids
    assert r.status_code == 400 and "chat id" in r.json()["detail"].lower()
    assert called["getMe"] is False  # failed before validating/writing
    assert "TELEGRAM_BOT_TOKEN" not in agent_env["env"].read_text(encoding="utf-8")  # no write


def test_recent_chats_uses_pasted_token_no_persist(agent_env, monkeypatch):
    """review M2: getUpdates uses the token from the request (not persisted) so a chat id can
    be picked BEFORE binding — breaking the bind-needs-chat / getUpdates-needs-token deadlock."""
    monkeypatch.setattr(
        "src.actions.telegram_write.api_call",
        lambda token, method, payload=None: [
            {"message": {"chat": {"id": 555, "username": "ceo"}}}
        ],
    )
    r = _client().post("/api/agents/acme/telegram/updates", json={"token": "123:ABC"})
    assert r.status_code == 200
    assert r.json()["chats"] == [{"id": "555", "name": "ceo"}]
    # nothing persisted
    assert "TELEGRAM_BOT_TOKEN" not in agent_env["env"].read_text(encoding="utf-8")
