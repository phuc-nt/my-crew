"""Zalo business fleet P4: account-store credential routes. Offline.

Load-bearing:
- POST/PUT a credential value never round-trips it in the response.
- List/delete work; delete of a never-stored account is not an error.
- Invalid account id -> 400, not a 500/crash.
- `/api/connections` (GET) surfaces the account list, still never a value.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr("my_crew.server.env_writer._ENV_PATH", env)
    monkeypatch.setattr("my_crew.config.settings.MY_CREW_HOME", tmp_path)
    data_dir = tmp_path / ".data"
    data_dir.mkdir()
    monkeypatch.setattr("my_crew.config.credential_store.DATA_DIR", data_dir)
    from my_crew.server import routes_connections

    monkeypatch.setattr(routes_connections, "integration_checks", lambda: {"checks": []})
    monkeypatch.setattr(routes_connections, "_needs_restart", False)
    monkeypatch.delenv("MY_CREW_CRED_KEY", raising=False)
    yield env


def _client():
    from my_crew.server.app import create_app

    return TestClient(create_app())


_SECRET = "zalo-oa-super-secret-token"


def test_put_credential_value_never_in_response(env_file):
    r = _client().put("/api/connections/accounts/zalo-oa-main", json={"value": {"token": _SECRET}})
    assert r.status_code == 200
    assert _SECRET not in r.text
    assert r.json() == {"ok": True, "account_id": "zalo-oa-main"}


def test_put_then_list_shows_account_id_only(env_file):
    _client().put("/api/connections/accounts/acc1", json={"value": {"token": "x"}})
    r = _client().get("/api/connections/accounts")
    assert r.status_code == 200
    assert r.json() == {"accounts": ["acc1"]}


def test_put_empty_value_rejected(env_file):
    r = _client().put("/api/connections/accounts/acc1", json={"value": {}})
    assert r.status_code == 400


def test_put_invalid_account_id_rejected(env_file):
    r = _client().put("/api/connections/accounts/UPPER_NOT_ALLOWED", json={"value": {"token": "x"}})
    assert r.status_code == 400


def test_delete_existing_account(env_file):
    _client().put("/api/connections/accounts/acc1", json={"value": {"token": "x"}})
    r = _client().delete("/api/connections/accounts/acc1")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "account_id": "acc1", "deleted": True}
    assert _client().get("/api/connections/accounts").json() == {"accounts": []}


def test_delete_nonexistent_account_not_an_error(env_file):
    r = _client().delete("/api/connections/accounts/never-existed")
    assert r.status_code == 200
    assert r.json()["deleted"] is False


def test_connections_overview_includes_accounts_never_values(env_file):
    _client().put("/api/connections/accounts/acc1", json={"value": {"token": _SECRET}})
    r = _client().get("/api/connections")
    assert r.status_code == 200
    assert _SECRET not in r.text
    assert r.json()["accounts"] == ["acc1"]
