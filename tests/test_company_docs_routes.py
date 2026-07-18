"""v7 M19 S3/S4: Company Docs library CRUD + per-agent opt-in routes. Offline.

Load-bearing:
- Library CRUD: create derives a slug, PUT edits, DELETE removes; create-collision 409.
- Per-agent opt-in writes `company_docs:` to profile.yaml; an unknown slug is rejected.
- Both surfaces are auth-gated (not in the public prefix list) — asserted structurally.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _client():
    from my_crew.server.app import create_app

    return TestClient(create_app())


@pytest.fixture
def docs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("my_crew.company_docs.store._DOCS_DIR", tmp_path / "company-docs")
    return tmp_path / "company-docs"


# --- library CRUD (S3) ---


def test_create_list_get_update_delete(docs_dir):
    c = _client()
    r = c.post("/api/company-docs", json={"title": "Nghỉ phép", "body": "12 ngày",
                                          "updated": "2026-07-04"})
    assert r.status_code == 200
    slug = r.json()["slug"]
    assert slug == "nghi-phep"  # VN diacritics folded to ascii

    assert len(c.get("/api/company-docs").json()["docs"]) == 1
    got = c.get(f"/api/company-docs/{slug}")
    assert got.status_code == 200 and got.json()["body"] == "12 ngày"

    r = c.put(f"/api/company-docs/{slug}", json={"title": "Nghỉ phép", "body": "15 ngày",
                                                 "updated": "2026-07-05"})
    assert r.status_code == 200 and r.json()["body"] == "15 ngày"

    assert c.delete(f"/api/company-docs/{slug}").status_code == 200
    assert c.get(f"/api/company-docs/{slug}").status_code == 404


def test_create_requires_title(docs_dir):
    assert _client().post("/api/company-docs", json={"title": "  "}).status_code == 400


def test_create_collision_409(docs_dir):
    c = _client()
    c.post("/api/company-docs", json={"title": "Leave Policy"})
    r = c.post("/api/company-docs", json={"title": "Leave Policy"})
    assert r.status_code == 409


def test_update_missing_404(docs_dir):
    assert _client().put("/api/company-docs/nope", json={"title": "x"}).status_code == 404


def test_delete_missing_404(docs_dir):
    assert _client().delete("/api/company-docs/nope").status_code == 404


def test_get_invalid_slug_400(docs_dir):
    assert _client().get("/api/company-docs/Bad%20Slug").status_code == 400


# --- per-agent opt-in (S4) ---


@pytest.fixture
def stub_agent(monkeypatch, tmp_path):
    """A real acme profile.yaml on a patched profiles dir + intercepted read/save."""
    prof = tmp_path / "acme"
    prof.mkdir()
    (prof / "profile.yaml").write_text("name: acme\ndomain: pm\n", encoding="utf-8")
    monkeypatch.setattr("my_crew.profile.loader._PROFILES_DIR", tmp_path)
    from types import SimpleNamespace

    store_yaml = {"text": "name: acme\ndomain: pm\n"}
    monkeypatch.setattr("my_crew.profile.loader.load_profile",
                        lambda pid, **k: SimpleNamespace(company_docs=()))
    monkeypatch.setattr("my_crew.server.profile_editor.read_profile_files",
                        lambda aid: {"profile": store_yaml["text"]})
    monkeypatch.setattr("my_crew.server.profile_editor.save_profile_yaml",
                        lambda aid, text: store_yaml.update(text=text))
    return store_yaml


def test_agent_company_docs_list_flags_selected(docs_dir, stub_agent):
    c = _client()
    c.post("/api/company-docs", json={"title": "Leave Policy"})
    r = c.get("/api/agents/acme/company-docs")
    assert r.status_code == 200
    assert all(d["selected"] is False for d in r.json()["docs"])


def test_agent_company_docs_put_writes_profile(docs_dir, stub_agent):
    c = _client()
    slug = c.post("/api/company-docs", json={"title": "Leave Policy"}).json()["slug"]
    r = c.put("/api/agents/acme/company-docs", json={"slugs": [slug]})
    assert r.status_code == 200 and r.json()["company_docs"] == [slug]
    assert slug in stub_agent["text"]


def test_agent_company_docs_put_rejects_unknown(docs_dir, stub_agent):
    r = _client().put("/api/agents/acme/company-docs", json={"slugs": ["ghost-doc"]})
    assert r.status_code == 400
    assert "ghost-doc" in r.json()["detail"]


def test_company_docs_not_public():
    # structural red line: the library/opt-in surfaces are NOT in the public prefix list.
    from my_crew.server.auth import _PUBLIC_PREFIXES

    assert not any("company-docs" in p for p in _PUBLIC_PREFIXES)
