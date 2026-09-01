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
    out = template_create.create_from_template("researcher")
    assert out["id"] == "researcher"
    doc = _profile_doc(profiles, "researcher")
    assert doc["domain"] == "office"
    # the "tool gắn sẵn" contract: flags + runtime tier land in the created profile
    assert doc["web_search"] is True
    assert doc["agent_runtime"]["kind"] == "deep_agent"
    # persona (SOUL.md) scaffolded
    assert (profiles / "researcher" / "SOUL.md").exists()


def test_create_from_template_lands_disabled(tmp_world):
    """Plan invariant: one-click creates are OFF until the operator enables them —
    both the registry master switch and the profile flag."""
    registry, profiles, _ = tmp_world
    template_create.create_from_template("content")
    assert _profile_doc(profiles, "content")["enabled"] is False
    reg = yaml.safe_load(registry.read_text())
    entry = next(e for e in reg["agents"] if e["id"] == "content")
    assert entry["enabled"] is False
    # the wizard path keeps its historical enabled-True default
    agent_create.create_agent({
        "id": "wiz", "name": "Wiz", "domain": "office", "reports": [],
        "schedule": {}, "bindings": {},
    })
    assert _profile_doc(profiles, "wiz")["enabled"] is True


def test_create_from_template_hint_is_bilingual(tmp_world):
    """The "Agent is OFF" hint carries both Vietnamese (primary) and a short English
    line — this codebase's other first-run BE strings stay Vietnamese-only, so this is
    scoped to exactly this hint, not a general i18n mechanism."""
    result = template_create.create_from_template("content")
    assert "Agent đang TẮT" in result["hint"]
    assert "Agent is OFF" in result["hint"]


def test_create_from_template_records_template_role_and_no_copy(tmp_world):
    """v36 P2: skills are NOT copied — the agent records `template_role` and loads skills
    live from the template dir (verified in test_template_live_skills.py)."""
    import yaml

    _, profiles, _ = tmp_world
    template_create.create_from_template("researcher")
    # No skills copied into the created agent's own dir.
    assert not list((profiles / "researcher" / "skills").glob("*.md"))
    # profile.yaml records the role so load_skill_pool loads template skills live.
    doc = yaml.safe_load((profiles / "researcher" / "profile.yaml").read_text(encoding="utf-8"))
    assert doc["template_role"] == "researcher"


def test_create_from_template_id_override_and_conflict(tmp_world):
    template_create.create_from_template("content", agent_id="content-2")
    with pytest.raises(agent_create.ConflictError):
        template_create.create_from_template("content", agent_id="content-2")


def test_unknown_or_traversal_role_id_rejected(tmp_world):
    with pytest.raises(template_create.TemplateError):
        template_create.create_from_template("khong-ton-tai")
    with pytest.raises(template_create.TemplateError):
        template_create.create_from_template("../default")


# --- crew ---


def test_crew_create_full_then_idempotent_rerun(tmp_world):
    registry, profiles, company = tmp_world
    out = template_create.create_crew()
    assert set(out["created"]) == {"coordinator", "researcher", "content",
                                   "analyst", "qa"}
    assert out["failed"] == [] and out["skipped"] == []
    assert out["coordinator_id"] == "coordinator"
    assert yaml.safe_load(company.read_text())["coordinator_id"] == "coordinator"
    # re-run: everything already exists → all skipped, nothing fails, coordinator kept
    again = template_create.create_crew()
    assert again["created"] == [] and set(again["skipped"]) == set(out["created"])
    assert again["coordinator_id"] == "coordinator"


def test_crew_partial_existing_member_is_skipped_not_abort(tmp_world):
    template_create.create_from_template("content")
    out = template_create.create_crew()
    assert "content" in out["skipped"]
    assert "researcher" in out["created"] and out["failed"] == []


def test_crew_never_clobbers_existing_coordinator(tmp_world, monkeypatch):
    from my_crew.runtime.company import save_company

    # CEO already picked a coordinator by hand — the crew must not overwrite it.
    template_create.create_from_template("analyst")
    save_company("Cty", "analyst")
    out = template_create.create_crew()
    assert out["coordinator_id"] == "analyst"


def test_crew_preview_matches_manifest(tmp_world):
    template_create.create_from_template("qa")
    preview = template_create.crew_preview()
    ids = {m["role_id"]: m for m in preview["members"]}
    assert ids["qa"]["exists"] is True
    assert ids["coordinator"]["exists"] is False
    assert preview["coordinator"] == "coordinator"
    assert preview["coordinator_already_set"] is False


# --- v71: more than one crew ---


def test_list_crews_offers_office_first_then_personal(tmp_world):
    crews = template_create.list_crews()
    ids = [c["id"] for c in crews]
    assert ids[0] == template_create.DEFAULT_CREW_ID == "office"
    assert "personal" in ids
    assert all(c["name"] and c["member_count"] > 0 for c in crews)


def test_personal_crew_adopts_pong_under_its_own_id(tmp_world):
    """The `{role, id}` member form creates the personal-assistant template AS `pong`,
    so the official assistant is adopted rather than duplicated under the role name."""
    _, profiles, _ = tmp_world
    out = template_create.create_crew("personal")
    assert out["crew_id"] == "personal"
    assert "pong" in out["created"] and "personal-assistant" not in out["created"]
    doc = _profile_doc(profiles, "pong")
    assert doc["domain"] == "personal" and doc["template_role"] == "personal-assistant"


def test_personal_crew_skips_an_already_adopted_pong(tmp_world):
    """Skip is keyed on the AGENT id: `pong` exists, so it is skipped even though the
    role template `personal-assistant` was never instantiated under its own name."""
    template_create.create_from_template("personal-assistant", agent_id="pong")
    out = template_create.create_crew("personal")
    assert "pong" in out["skipped"] and out["failed"] == []
    assert "researcher" in out["created"]


def test_unknown_or_traversal_crew_id_rejected(tmp_world):
    for bad in ("ghost", "../office", "a/b"):
        with pytest.raises(template_create.TemplateError):
            template_create.create_crew(bad)


# --- routes (thin wrappers) ---


def test_routes_create_and_crew(tmp_world):
    client = TestClient(create_app())
    r = client.post("/api/agents/create-from-template", json={"role_id": "content"})
    assert r.status_code == 200 and r.json()["id"] == "content"
    # conflict maps to 409
    assert client.post("/api/agents/create-from-template",
                       json={"role_id": "content"}).status_code == 409
    # unknown template maps to 400
    assert client.post("/api/agents/create-from-template",
                       json={"role_id": "ghost"}).status_code == 400
    r = client.get("/api/crew/preview")
    assert r.status_code == 200 and len(r.json()["members"]) == 5
    r = client.post("/api/crew/create")
    assert r.status_code == 200
    body = r.json()
    assert "content" in body["skipped"] and body["failed"] == []


def test_routes_crew_id_selects_the_crew_and_defaults_to_office(tmp_world):
    """v71: a pre-v71 client sends no crew_id and must still get the office crew."""
    client = TestClient(create_app())
    assert client.get("/api/crew/preview").json()["crew_id"] == "office"

    listed = client.get("/api/crews").json()
    assert listed["default"] == "office"
    assert {"office", "personal"} <= {c["id"] for c in listed["crews"]}

    personal = client.get("/api/crew/preview?crew_id=personal").json()
    assert personal["crew_id"] == "personal"
    assert "pong" in {m["role_id"] for m in personal["members"]}

    assert client.get("/api/crew/preview?crew_id=ghost").status_code == 400
    assert client.post("/api/crew/create?crew_id=ghost").status_code == 400

    created = client.post("/api/crew/create?crew_id=personal").json()
    assert created["crew_id"] == "personal" and "pong" in created["created"]


def test_staff_templates_expose_v32_fields(tmp_world):
    client = TestClient(create_app())
    templates = {t["role_id"]: t for t in client.get("/api/staff-templates").json()["templates"]}
    assert templates["researcher"]["web_search"] is True
    assert templates["researcher"]["has_skills"] is True
    assert templates["coordinator"]["web_search"] is False
