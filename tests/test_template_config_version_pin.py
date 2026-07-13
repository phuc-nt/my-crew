"""v36 P3: template CONFIG version-pin — upgrade with review, keep user edits, backup.

Create records template_version + a config baseline. Upgrade re-applies only the fields
the user never customized (live == baseline), keeps the rest, and always backs up the
full profile.yaml first. Agents without template_role / without a baseline are handled
conservatively (out of scope / apply nothing).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from src.server import agent_create, template_create, template_upgrade

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def tmp_world(tmp_path, monkeypatch):
    """Isolated registry + profiles + templates dir with one role template we can bump."""
    from src.runtime import registry_edit

    registry = tmp_path / "registry.yaml"
    registry.write_text("agents:\n  - id: default\n    enabled: false\n", encoding="utf-8")
    profiles = tmp_path / "profiles"
    (profiles / "default").mkdir(parents=True)
    shutil.copyfile(_REPO / "profiles" / "default" / "profile.yaml",
                    profiles / "default" / "profile.yaml")
    company = tmp_path / "company.yaml"
    templates = tmp_path / "templates"
    role = templates / "vai-thu"
    (role / "skills").mkdir(parents=True)
    (role / "template.yaml").write_text(
        "role: Thử\ndomain: office\nreports: []\nweb_search: false\nversion: 1\n",
        encoding="utf-8")

    monkeypatch.setattr("src.runtime.agent_paths.DATA_DIR", tmp_path / ".data")
    monkeypatch.setattr(agent_create, "_REGISTRY_PATH", registry)
    monkeypatch.setattr(agent_create, "_PROFILES_DIR", profiles)
    monkeypatch.setattr(registry_edit, "_REGISTRY_PATH", registry)
    monkeypatch.setattr("src.runtime.registry._REGISTRY_PATH", registry)
    monkeypatch.setattr("src.runtime.company._COMPANY_PATH", company)
    monkeypatch.setattr("src.server.profile_editor._PROFILES_DIR", profiles)
    monkeypatch.setattr("src.profile.loader._PROFILES_DIR", profiles)
    monkeypatch.setattr("src.packs.registry._PROFILES_DIR", profiles, raising=False)
    monkeypatch.setattr("src.server.routes_company._TEMPLATES_DIR", templates)
    monkeypatch.setattr("src.server.template_create._TEMPLATES_DIR", templates)
    return profiles, templates, role


def _bump_template(role: Path, **fields):
    doc = yaml.safe_load((role / "template.yaml").read_text(encoding="utf-8"))
    doc.update(fields)
    (role / "template.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")


def _read(profiles: Path, agent_id: str) -> dict:
    return yaml.safe_load((profiles / agent_id / "profile.yaml").read_text(encoding="utf-8"))


def test_create_records_version_and_baseline(tmp_world):
    profiles, _, _ = tmp_world
    template_create.create_from_template("vai-thu")
    doc = _read(profiles, "vai-thu")
    assert doc["template_role"] == "vai-thu"
    assert doc["template_version"] == 1
    assert doc["template_config_applied"]["web_search"] is False


def test_upgrade_applies_untouched_field(tmp_world):
    profiles, _, role = tmp_world
    template_create.create_from_template("vai-thu")
    _bump_template(role, version=2, web_search=True)  # config changed
    plan = template_upgrade.preview_upgrade("vai-thu")
    assert plan["apply"] == {"web_search": True}
    assert plan["latest_version"] == 2 and plan["applied_version"] == 1
    result = template_upgrade.apply_upgrade("vai-thu")
    doc = _read(profiles, "vai-thu")
    assert doc["web_search"] is True
    assert doc["template_version"] == 2
    assert result["backup"].startswith("profile.yaml.bak-")
    assert (profiles / "vai-thu" / result["backup"]).exists()


def test_upgrade_keeps_user_customized_field(tmp_world):
    profiles, _, role = tmp_world
    template_create.create_from_template("vai-thu")
    # User turns web_search ON by hand (differs from baseline False).
    doc = _read(profiles, "vai-thu")
    doc["web_search"] = True
    (profiles / "vai-thu" / "profile.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    # Template later sets web_search True too — but since the user already customized it,
    # it must be KEPT (reported), not silently "applied".
    _bump_template(role, version=2, web_search=True)
    plan = template_upgrade.preview_upgrade("vai-thu")
    assert "web_search" in plan["keep"]
    assert plan["apply"] == {}


def test_upgrade_backup_preserves_original(tmp_world):
    profiles, _, role = tmp_world
    template_create.create_from_template("vai-thu")
    before = (profiles / "vai-thu" / "profile.yaml").read_text(encoding="utf-8")
    _bump_template(role, version=2, web_search=True)
    result = template_upgrade.apply_upgrade("vai-thu")
    backup = (profiles / "vai-thu" / result["backup"]).read_text(encoding="utf-8")
    assert backup == before  # exact pre-upgrade snapshot


def test_status_flags_upgradable(tmp_world, monkeypatch):
    profiles, _, role = tmp_world
    template_create.create_from_template("vai-thu")
    monkeypatch.setattr("src.runtime.registry.load_registry",
                        lambda: (type("E", (), {"id": "vai-thu"})(),))
    _bump_template(role, version=3)
    rows = template_upgrade.agent_upgrade_status()
    row = next(r for r in rows if r["agent_id"] == "vai-thu")
    assert row["upgradable"] is True and row["latest_version"] == 3


def test_non_template_agent_rejected(tmp_world):
    with pytest.raises(ValueError, match="không gắn template"):
        template_upgrade.preview_upgrade("default")


def test_apply_goes_through_save_door_and_raises_on_invalid_config(tmp_world, monkeypatch):
    """v36 P3 acceptance #4: apply writes THROUGH save_profile_yaml (the validate door),
    so if that door rejects the merged config the exception propagates and — because the
    backup is written first — the original is recoverable. We force the door to reject to
    prove apply doesn't bypass it."""
    profiles, _, role = tmp_world
    template_create.create_from_template("vai-thu")
    before = (profiles / "vai-thu" / "profile.yaml").read_text(encoding="utf-8")
    _bump_template(role, version=2, web_search=True)

    def _reject(agent_id, new_text):
        raise RuntimeError("cấu hình không hợp lệ (giả lập)")

    monkeypatch.setattr("src.server.profile_editor.save_profile_yaml", _reject)
    with pytest.raises(RuntimeError):
        template_upgrade.apply_upgrade("vai-thu")
    # The live profile is untouched (save was rejected), and the pre-write backup exists
    # so the operator can recover — the backup is written BEFORE the save-door call.
    assert (profiles / "vai-thu" / "profile.yaml").read_text(encoding="utf-8") == before
    backups = list((profiles / "vai-thu").glob("profile.yaml.bak-*"))
    assert backups and backups[0].read_text(encoding="utf-8") == before


def test_missing_baseline_keeps_everything(tmp_world):
    profiles, _, role = tmp_world
    template_create.create_from_template("vai-thu")
    # Simulate a pre-P3 agent: strip the baseline.
    doc = _read(profiles, "vai-thu")
    doc.pop("template_config_applied", None)
    (profiles / "vai-thu" / "profile.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    _bump_template(role, version=2, web_search=True)
    plan = template_upgrade.preview_upgrade("vai-thu")
    assert plan["apply"] == {}  # no baseline ⇒ can't prove un-customized ⇒ keep all
    assert "web_search" in plan["keep"]
