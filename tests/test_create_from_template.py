"""v32 P2: one-click create-from-template + crew bootstrap — server-side spec build
(client can't smuggle config), tool flags/skills landing in the created profile,
per-member independence + idempotent re-run, coordinator wiring that never clobbers.

Uses the REAL repo templates (`profiles/templates/` is committed repo data) against a
tmp registry/profiles/company world — the shipped templates themselves are under test.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from my_crew.runtime import registry_edit
from my_crew.server import agent_create, template_create
from my_crew.server.app import create_app

_REPO = Path(__file__).resolve().parents[1]
_REGISTRY_TEXT = """\
# Agent registry — comments must survive edits.
agents:
  - id: default
    enabled: false
"""


@pytest.fixture()
def tmp_world(tmp_path, monkeypatch):
    registry = tmp_path / "registry.yaml"
    registry.write_text(_REGISTRY_TEXT, encoding="utf-8")
    profiles = tmp_path / "profiles"
    (profiles / "default").mkdir(parents=True)
    shutil.copyfile(_REPO / "profiles" / "default" / "profile.yaml",
                    profiles / "default" / "profile.yaml")
    company = tmp_path / "company.yaml"
    monkeypatch.setattr("my_crew.runtime.agent_paths.DATA_DIR", tmp_path / ".data")
    monkeypatch.setattr(agent_create, "_REGISTRY_PATH", registry)
    monkeypatch.setattr(agent_create, "_PROFILES_DIR", profiles)
    monkeypatch.setattr(registry_edit, "_REGISTRY_PATH", registry)
    monkeypatch.setattr("my_crew.profile.loader._PROFILES_DIR", profiles)
    monkeypatch.setattr("my_crew.runtime.registry._REGISTRY_PATH", registry)
    monkeypatch.setattr("my_crew.runtime.company._COMPANY_PATH", company)
    # per-agent skills dir resolves under profiles/<id>/skills via the pack registry
    monkeypatch.setattr("my_crew.packs.registry._PROFILES_DIR", profiles, raising=False)
    return registry, profiles, company


def _profile_doc(profiles: Path, agent_id: str) -> dict:
    return yaml.safe_load((profiles / agent_id / "profile.yaml").read_text())


# --- single one-click create ---


def test_create_from_template_carries_standard_config(tmp_world):
    _, profiles, _ = tmp_world
    out = template_create.create_from_template("nghien-cuu")
    assert out["id"] == "nghien-cuu"
    doc = _profile_doc(profiles, "nghien-cuu")
    assert doc["domain"] == "office"
    # the "tool gắn sẵn" contract: flags + runtime tier land in the created profile
    assert doc["web_search"] is True
    assert doc["academic_search"] is True
    assert doc["agent_runtime"]["kind"] == "deep_agent"
    # persona (SOUL.md) scaffolded
    assert (profiles / "nghien-cuu" / "SOUL.md").exists()


def test_create_from_template_lands_disabled(tmp_world):
    """Plan invariant: one-click creates are OFF until the operator enables them —
    both the registry master switch and the profile flag."""
    registry, profiles, _ = tmp_world
    template_create.create_from_template("noi-dung")
    assert _profile_doc(profiles, "noi-dung")["enabled"] is False
    reg = yaml.safe_load(registry.read_text())
    entry = next(e for e in reg["agents"] if e["id"] == "noi-dung")
    assert entry["enabled"] is False
    # the wizard path keeps its historical enabled-True default
    agent_create.create_agent({
        "id": "wiz", "name": "Wiz", "domain": "office", "reports": [],
        "schedule": {}, "bindings": {},
    })
    assert _profile_doc(profiles, "wiz")["enabled"] is True


def test_create_from_template_records_template_role_and_no_copy(tmp_world):
    """v36 P2: skills are NOT copied — the agent records `template_role` and loads skills
    live from the template dir (verified in test_template_live_skills.py)."""
    import yaml

    _, profiles, _ = tmp_world
    template_create.create_from_template("nghien-cuu")
    # No skills copied into the created agent's own dir.
    assert not list((profiles / "nghien-cuu" / "skills").glob("*.md"))
    # profile.yaml records the role so load_skill_pool loads template skills live.
    doc = yaml.safe_load((profiles / "nghien-cuu" / "profile.yaml").read_text(encoding="utf-8"))
    assert doc["template_role"] == "nghien-cuu"


def test_create_from_template_id_override_and_conflict(tmp_world):
    template_create.create_from_template("noi-dung", agent_id="noi-dung-2")
    with pytest.raises(agent_create.ConflictError):
        template_create.create_from_template("noi-dung", agent_id="noi-dung-2")


def test_unknown_or_traversal_role_id_rejected(tmp_world):
    with pytest.raises(template_create.TemplateError):
        template_create.create_from_template("khong-ton-tai")
    with pytest.raises(template_create.TemplateError):
        template_create.create_from_template("../default")


# --- crew ---


def test_crew_create_full_then_idempotent_rerun(tmp_world):
    registry, profiles, company = tmp_world
    out = template_create.create_crew()
    assert set(out["created"]) == {"truong-phong", "nghien-cuu", "noi-dung",
                                   "phan-tich", "kiem-dinh"}
    assert out["failed"] == [] and out["skipped"] == []
    assert out["coordinator_id"] == "truong-phong"
    assert yaml.safe_load(company.read_text())["coordinator_id"] == "truong-phong"
    # re-run: everything already exists → all skipped, nothing fails, coordinator kept
    again = template_create.create_crew()
    assert again["created"] == [] and set(again["skipped"]) == set(out["created"])
    assert again["coordinator_id"] == "truong-phong"


def test_crew_partial_existing_member_is_skipped_not_abort(tmp_world):
    template_create.create_from_template("noi-dung")
    out = template_create.create_crew()
    assert "noi-dung" in out["skipped"]
    assert "nghien-cuu" in out["created"] and out["failed"] == []


def test_crew_never_clobbers_existing_coordinator(tmp_world, monkeypatch):
    from my_crew.runtime.company import save_company

    # CEO already picked a coordinator by hand — the crew must not overwrite it.
    template_create.create_from_template("phan-tich")
    save_company("Cty", "phan-tich")
    out = template_create.create_crew()
    assert out["coordinator_id"] == "phan-tich"


def test_crew_preview_matches_manifest(tmp_world):
    template_create.create_from_template("kiem-dinh")
    preview = template_create.crew_preview()
    ids = {m["role_id"]: m for m in preview["members"]}
    assert ids["kiem-dinh"]["exists"] is True
    assert ids["truong-phong"]["exists"] is False
    assert preview["coordinator"] == "truong-phong"
    assert preview["coordinator_already_set"] is False


# --- routes (thin wrappers) ---


def test_routes_create_and_crew(tmp_world):
    client = TestClient(create_app())
    r = client.post("/api/agents/create-from-template", json={"role_id": "noi-dung"})
    assert r.status_code == 200 and r.json()["id"] == "noi-dung"
    # conflict maps to 409
    assert client.post("/api/agents/create-from-template",
                       json={"role_id": "noi-dung"}).status_code == 409
    # unknown template maps to 400
    assert client.post("/api/agents/create-from-template",
                       json={"role_id": "ghost"}).status_code == 400
    r = client.get("/api/crew/preview")
    assert r.status_code == 200 and len(r.json()["members"]) == 5
    r = client.post("/api/crew/create")
    assert r.status_code == 200
    body = r.json()
    assert "noi-dung" in body["skipped"] and body["failed"] == []


def test_staff_templates_expose_v32_fields(tmp_world):
    client = TestClient(create_app())
    templates = {t["role_id"]: t for t in client.get("/api/staff-templates").json()["templates"]}
    assert templates["nghien-cuu"]["academic_search"] is True
    assert templates["nghien-cuu"]["has_skills"] is True
    assert templates["truong-phong"]["academic_search"] is False
