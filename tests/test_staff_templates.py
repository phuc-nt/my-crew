"""/api/company + /api/staff-templates — config-only routes, auth-protected.

Offline. Company writes run against a tmp company.yaml (never the committed file);
staff-templates reads the REAL profiles/templates/ dir (read-only, no import) to prove
the shipped sample template loads through the real route.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from my_crew.runtime import company as company_module
from my_crew.server import auth, routes_company
from my_crew.server.app import create_app


@pytest.fixture()
def tmp_company(tmp_path, monkeypatch):
    path = tmp_path / "company.yaml"
    monkeypatch.setattr(company_module, "_COMPANY_PATH", path)
    return path


@pytest.fixture()
def client(tmp_company):
    return TestClient(create_app())


# --- GET /api/company ---


def test_get_company_default_when_missing(client):
    r = client.get("/api/company")
    assert r.status_code == 200
    body = r.json()
    assert body == {"name": "", "coordinator_id": None, "team_task_cap_usd": 2.0,
                    "team_task_concurrency": 2, "team_task_auto_confirm": False}


# --- POST /api/company ---


def test_post_company_writes_name_and_no_coordinator(client, tmp_company):
    r = client.post("/api/company", json={"name": "Acme", "coordinator_id": None})
    assert r.status_code == 200
    assert r.json() == {"name": "Acme", "coordinator_id": None, "team_task_cap_usd": 2.0,
                        "team_task_concurrency": 2, "team_task_auto_confirm": False}
    assert tmp_company.exists()
    assert client.get("/api/company").json()["name"] == "Acme"


def test_post_company_accepts_known_coordinator(client, monkeypatch):
    from my_crew.runtime.registry import RegistryEntry

    monkeypatch.setattr(
        routes_company, "load_registry", lambda: (RegistryEntry(id="default", enabled=True),)
    )
    r = client.post("/api/company", json={"name": "Acme", "coordinator_id": "default"})
    assert r.status_code == 200
    assert r.json()["coordinator_id"] == "default"


def test_post_company_rejects_unknown_coordinator(client, monkeypatch):
    from my_crew.runtime.registry import RegistryEntry

    monkeypatch.setattr(
        routes_company, "load_registry", lambda: (RegistryEntry(id="default", enabled=True),)
    )
    r = client.post("/api/company", json={"name": "Acme", "coordinator_id": "ghost"})
    assert r.status_code == 400
    assert "ghost" in r.json()["detail"]


def test_post_company_rejects_non_positive_cap(client):
    r = client.post("/api/company", json={"name": "Acme", "team_task_cap_usd": 0})
    assert r.status_code == 400


# --- GET /api/staff-templates ---


def test_staff_templates_lists_sample_pm_template(client):
    r = client.get("/api/staff-templates")
    assert r.status_code == 200
    templates = r.json()["templates"]
    assert len(templates) >= 1
    pm = next(t for t in templates if t["domain"] == "pm")
    assert pm["role_id"] == "pm-coordinator"
    assert pm["role"]
    assert pm["reports"] == ["daily", "weekly"]
    assert pm["bindings_hint"] == ["jira", "slack"]
    assert "skills" not in pm
    assert "Điều phối dự án" in pm["persona"]  # persona prefill present
    assert pm["web_search"] is False  # opt-in flag defaults off for non-research roles


def test_staff_templates_research_role_ships_web_search_on(client):
    templates = client.get("/api/staff-templates").json()["templates"]
    research = next(t for t in templates if t["role_id"] == "nghien-cuu")
    assert research["web_search"] is True
    # Every other role stays opt-out — the flag never defaults on across the gallery.
    assert all(not t["web_search"] for t in templates if t["role_id"] != "nghien-cuu")


def test_staff_templates_skips_broken_manifest(client, monkeypatch, tmp_path):
    good = tmp_path / "templates" / "ok-role"
    good.mkdir(parents=True)
    (good / "template.yaml").write_text("role: OK\ndomain: pm\nreports: []\n", encoding="utf-8")
    bad = tmp_path / "templates" / "broken-role"
    bad.mkdir(parents=True)
    (bad / "template.yaml").write_text("not: [valid: yaml\n", encoding="utf-8")
    monkeypatch.setattr(routes_company, "_TEMPLATES_DIR", tmp_path / "templates")

    r = client.get("/api/staff-templates")
    assert r.status_code == 200
    ids = [t["role_id"] for t in r.json()["templates"]]
    assert ids == ["ok-role"]


def test_staff_templates_empty_dir_returns_empty_list(client, monkeypatch, tmp_path):
    monkeypatch.setattr(routes_company, "_TEMPLATES_DIR", tmp_path / "no-such-dir")
    r = client.get("/api/staff-templates")
    assert r.status_code == 200
    assert r.json() == {"templates": []}


# --- auth protection ---


@pytest.fixture
def auth_env(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_USERNAME", "ceo")
    monkeypatch.setenv("WEB_AUTH_PASSWORD_HASH", auth.hash_password("s3cret"))
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    auth._login_attempts.clear()


def test_company_and_templates_require_auth_when_enabled(auth_env, tmp_company):
    c = TestClient(create_app())
    assert c.get("/api/company").status_code == 401
    assert c.post("/api/company", json={"name": "Acme"}).status_code == 401
    assert c.get("/api/staff-templates").status_code == 401
