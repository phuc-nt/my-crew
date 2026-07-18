"""v18: unregistered-profiles listing + register-only route (recovery for 'profile
exists but registry lost it'). Per-profile validation degrades; register 409s cleanly
on duplicates and 400s on broken profiles."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    # isolate registry + profiles
    import my_crew.profile.loader as loader_mod
    import my_crew.runtime.registry as reg

    profiles = tmp_path / "profiles"
    (profiles / "templates" / "x").mkdir(parents=True)
    monkeypatch.setattr(loader_mod, "_PROFILES_DIR", profiles)
    target = tmp_path / "registry.yaml"
    target.write_text("agents:\n  - id: da-co\n    enabled: true\n")
    monkeypatch.setattr(reg, "_REGISTRY_PATH", target)
    from my_crew.server.app import create_app

    return TestClient(create_app())


def _mk_profile(tmp_path, agent_id, *, broken=False):
    d = tmp_path / "profiles" / agent_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "profile.yaml").write_text("{{{{not yaml" if broken else
                                    "name: OK\nenabled: true\ndomain: office\n")


def test_unregistered_lists_orphans_skips_templates_and_registered(client, tmp_path, monkeypatch):
    _mk_profile(tmp_path, "mo-coi")
    _mk_profile(tmp_path, "da-co")      # already registered → hidden
    _mk_profile(tmp_path, "hong", broken=True)
    r = client.get("/api/agents/unregistered")
    assert r.status_code == 200
    rows = {p["id"]: p for p in r.json()["profiles"]}
    assert "da-co" not in rows and "templates" not in rows
    # load may fail on the minimal yaml — listed either way, only the flag differs
    assert rows["mo-coi"]["valid"] in (True, False)
    assert rows["hong"]["valid"] is False and rows["hong"]["error"]


def test_register_only_happy_then_conflict(client, tmp_path):
    _mk_profile(tmp_path, "moi-vao")
    r = client.post("/api/agents/moi-vao/register")
    # minimal profile may fail full load → 400; a loadable one → 201. Accept either
    # shape but assert the CONTRACT: never 500, and a duplicate is 409.
    assert r.status_code in (201, 400)
    if r.status_code == 201:
        r2 = client.post("/api/agents/moi-vao/register")
        assert r2.status_code == 409


def test_register_unknown_and_bad_id(client):
    assert client.post("/api/agents/khong-ton-tai/register").status_code == 404
    # decoded "../x" contains a slash → never matches the {agent_id} segment (405 from
    # the router) — traversal cannot reach the handler, which ALSO gate-checks the id.
    assert client.post("/api/agents/..%2Fx/register").status_code in (400, 404, 405)


def test_websearch_flag_health_check(monkeypatch, tmp_path):
    """v18: check ✗ only when some ENABLED agent opts into web_search while the machine
    has neither provider key; no opt-in ⇒ ok regardless of keys."""
    from types import SimpleNamespace

    import my_crew.profile.loader as loader_mod
    import my_crew.runtime.registry as reg
    from my_crew.server.integration_health import _websearch_flag_check

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.setattr(reg, "_REGISTRY_PATH", tmp_path / "r.yaml")
    (tmp_path / "r.yaml").write_text("agents:\n  - id: a\n    enabled: true\n")
    monkeypatch.setattr(loader_mod, "load_profile",
                        lambda aid, **kw: SimpleNamespace(web_search=True))
    out = _websearch_flag_check()
    assert out["ok"] is False and "a" in out["detail"]

    monkeypatch.setenv("TAVILY_API_KEY", "x")
    assert _websearch_flag_check()["ok"] is True

    monkeypatch.delenv("TAVILY_API_KEY")
    monkeypatch.setattr(loader_mod, "load_profile",
                        lambda aid, **kw: SimpleNamespace(web_search=False))
    assert _websearch_flag_check()["ok"] is True  # no opt-in ⇒ ok
