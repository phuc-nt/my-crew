"""v3 M7: agent admin API — packs list, create wizard, lifecycle, integration health.

Offline. Registry/profile mutations run against tmp copies (never the committed files);
the packs list reads the REAL domain-packs/ manifests (read-only, no import). The
load-bearing properties:

- create = the SAME scaffold+append primitives as `mpm agent register`, validated by the
  REAL config builders BEFORE any write (bad spec → 400, nothing on disk).
- lifecycle edits are validate-before-replace: a toggle/delete can never corrupt
  registry.yaml, and comments in the file survive.
- health output contains check ids/hints only — NEVER a secret value.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.runtime import registry_edit
from src.runtime.registry import load_registry
from src.server import agent_create
from src.server.app import create_app

_REPO = Path(__file__).resolve().parents[1]

_REGISTRY_TEXT = """\
# Agent registry — comments must survive edits.
agents:
  - id: default
    enabled: true
  - id: acme
    enabled: true
"""


@pytest.fixture()
def tmp_world(tmp_path, monkeypatch):
    """Tmp registry + profiles (with the real default template) + data dir."""
    registry = tmp_path / "registry.yaml"
    registry.write_text(_REGISTRY_TEXT, encoding="utf-8")
    profiles = tmp_path / "profiles"
    (profiles / "default").mkdir(parents=True)
    shutil.copyfile(
        _REPO / "profiles" / "default" / "profile.yaml",
        profiles / "default" / "profile.yaml",
    )
    monkeypatch.setattr("src.runtime.agent_paths.DATA_DIR", tmp_path / ".data")
    monkeypatch.setattr(agent_create, "_REGISTRY_PATH", registry)
    monkeypatch.setattr(agent_create, "_PROFILES_DIR", profiles)
    monkeypatch.setattr(registry_edit, "_REGISTRY_PATH", registry)
    monkeypatch.setattr("src.profile.loader._PROFILES_DIR", profiles)
    return registry, profiles


@pytest.fixture()
def client(tmp_world):
    return TestClient(create_app())


# --- packs list (S1) ---


def test_packs_lists_pm_and_hr(client):
    packs = {p["id"]: p for p in client.get("/api/packs").json()["packs"]}
    assert "pm" in packs and "hr" in packs
    assert "daily" in packs["pm"]["report_kinds"]
    assert packs["hr"]["report_kinds"] == ["headcount"]


# --- create (S2) ---

_GOOD_SPEC = {
    "id": "hr-team",
    "name": "HR Team",
    "domain": "hr",
    "reports": ["headcount"],
    "schedule": {"headcount": "0 9 * * 1"},
    "bindings": {"slack": {"report_channel": "C123"}},
    "persona": "Bạn là HR chuyên nghiệp.",
}


def test_create_scaffolds_profile_and_registry(client, tmp_world):
    registry, profiles = tmp_world
    res = client.post("/api/agents/create", json=_GOOD_SPEC)
    assert res.status_code == 201, res.text
    assert res.json()["created"]["id"] == "hr-team"
    # Registry gained the entry; existing entries + comments intact.
    entries = {e.id for e in load_registry(registry)}
    assert entries == {"default", "acme", "hr-team"}
    assert registry.read_text(encoding="utf-8").startswith("# Agent registry")
    # Profile dir scaffolded with the wizard's fields + persona SOUL.md.
    import yaml

    doc = yaml.safe_load((profiles / "hr-team" / "profile.yaml").read_text(encoding="utf-8"))
    assert doc["domain"] == "hr"
    assert doc["reports"] == ["headcount"]
    assert doc["schedule"] == {"headcount": "0 9 * * 1"}
    assert doc["bindings"]["slack"]["report_channel"] == "C123"
    assert "HR chuyên nghiệp" in (profiles / "hr-team" / "SOUL.md").read_text(encoding="utf-8")
    # The created profile is loadable by the real loader path (MEMORY.md etc. exist).
    assert (profiles / "hr-team" / "MEMORY.md").exists()


def test_create_accepts_empty_reports(client, tmp_world):
    # v12 M27: a staffer created from a team-task/office-role template has no scheduled
    # report kind of its own — create_agent must accept reports: [] (empty schedule too).
    _, profiles = tmp_world
    spec = {**_GOOD_SPEC, "id": "staffer-1", "reports": [], "schedule": {}}
    res = client.post("/api/agents/create", json=spec)
    assert res.status_code == 201, res.text
    assert res.json()["created"]["reports"] == []
    import yaml

    doc = yaml.safe_load((profiles / "staffer-1" / "profile.yaml").read_text(encoding="utf-8"))
    assert doc["reports"] == []
    # web_search was not requested — the opt-in key must not appear at all.
    assert "web_search" not in doc


def test_create_writes_web_search_opt_in(client, tmp_world):
    # The research-role template pre-fills web_search; the wizard forwards it and the
    # created profile carries the literal flag the loader reads (opt-in, default false).
    _, profiles = tmp_world
    spec = {**_GOOD_SPEC, "id": "researcher-1", "reports": [], "schedule": {},
            "web_search": True}
    res = client.post("/api/agents/create", json=spec)
    assert res.status_code == 201, res.text
    import yaml

    doc = yaml.safe_load(
        (profiles / "researcher-1" / "profile.yaml").read_text(encoding="utf-8")
    )
    assert doc["web_search"] is True


def test_create_writes_trust_mode_when_picked(client, tmp_world):
    # The wizard's explicit pick lands in safety.trust_mode; absent ⇒ the profile
    # inherits the company-wide default (TRUST_MODE env), so the key must not appear.
    _, profiles = tmp_world
    spec = {**_GOOD_SPEC, "id": "guarded-1", "reports": [], "schedule": {},
            "trust_mode": "guarded"}
    res = client.post("/api/agents/create", json=spec)
    assert res.status_code == 201, res.text
    import yaml

    doc = yaml.safe_load((profiles / "guarded-1" / "profile.yaml").read_text(encoding="utf-8"))
    assert doc["safety"]["trust_mode"] == "guarded"

    spec2 = {**_GOOD_SPEC, "id": "default-1", "reports": [], "schedule": {}}
    assert client.post("/api/agents/create", json=spec2).status_code == 201
    doc2 = yaml.safe_load((profiles / "default-1" / "profile.yaml").read_text(encoding="utf-8"))
    assert "trust_mode" not in doc2.get("safety", {})


def test_create_rejects_unknown_trust_mode(client, tmp_world):
    spec = {**_GOOD_SPEC, "id": "weird-1", "reports": [], "schedule": {},
            "trust_mode": "yolo"}
    res = client.post("/api/agents/create", json=spec)
    assert res.status_code == 400
    assert "trust_mode" in res.text


def test_create_writes_agent_runtime_opt_in(client, tmp_world):
    # v20.5: the wizard forwards the chosen runtime; the created profile carries agent_runtime
    # for a non-native choice, and omits it (native default) otherwise.
    _, profiles = tmp_world
    import yaml

    spec = {**_GOOD_SPEC, "id": "deep-1", "reports": [], "schedule": {},
            "agent_runtime": "create_agent"}
    assert client.post("/api/agents/create", json=spec).status_code == 201
    doc = yaml.safe_load((profiles / "deep-1" / "profile.yaml").read_text(encoding="utf-8"))
    assert doc["agent_runtime"] == "create_agent"

    spec2 = {**_GOOD_SPEC, "id": "nat-1", "reports": [], "schedule": {},
             "agent_runtime": "native"}
    assert client.post("/api/agents/create", json=spec2).status_code == 201
    doc2 = yaml.safe_load((profiles / "nat-1" / "profile.yaml").read_text(encoding="utf-8"))
    assert "agent_runtime" not in doc2  # native = default, omitted


def test_create_writes_deep_agent_runtime_mapping(client, tmp_world):
    # v27: a deep_agent is created with its sandbox mapping (not a bare string, which would be
    # DOA). The handler passes the mapping through and the loader round-trips it.
    _, profiles = tmp_world
    import yaml

    spec = {**_GOOD_SPEC, "id": "deep-map", "reports": [], "schedule": {},
            "agent_runtime": {"kind": "deep_agent", "sandbox": {"provider": "docker"}}}
    assert client.post("/api/agents/create", json=spec).status_code == 201
    doc = yaml.safe_load((profiles / "deep-map" / "profile.yaml").read_text(encoding="utf-8"))
    assert doc["agent_runtime"] == {"kind": "deep_agent", "sandbox": {"provider": "docker"}}


@pytest.mark.parametrize(
    ("patch", "fragment"),
    [
        ({"id": "Bad/Id"}, "id"),
        ({"domain": "nope"}, "unknown domain"),
        ({"reports": ["daily"]}, "not served"),
        ({"schedule": {"headcount": "not-cron"}}, "cron"),
        ({"schedule": {"weekly": "0 9 * * 1"}}, "not a selected"),
        ({"bindings": {"slack": {"hack": "x"}}}, "not settable"),
        ({"bindings": {"filesystem": {}}}, "unknown bindings server"),
    ],
)
def test_create_rejects_bad_spec_with_400_and_writes_nothing(
    client, tmp_world, patch, fragment
):
    registry, profiles = tmp_world
    res = client.post("/api/agents/create", json={**_GOOD_SPEC, **patch})
    assert res.status_code == 400, res.text
    assert fragment.lower() in res.json()["detail"].lower()
    assert not (profiles / "hr-team").exists()
    assert {e.id for e in load_registry(registry)} == {"default", "acme"}


def test_create_collision_is_409(client, tmp_world):
    assert client.post("/api/agents/create", json=_GOOD_SPEC).status_code == 201
    res = client.post("/api/agents/create", json=_GOOD_SPEC)
    assert res.status_code == 409


def test_create_rolls_back_profile_dir_when_registry_append_fails(tmp_world, monkeypatch):
    registry, profiles = tmp_world

    def _boom(reg, agent_id, **kwargs):
        raise RuntimeError("append failed")

    monkeypatch.setattr(agent_create, "append_registry", _boom)
    with pytest.raises(RuntimeError):
        agent_create.create_agent(dict(_GOOD_SPEC))
    assert not (profiles / "hr-team").exists()  # no orphan profile dir


def test_create_stakeholder_channel_cross_check_maps_to_400(client):
    spec = {
        **_GOOD_SPEC,
        "bindings": {"slack": {"stakeholder_channel": "C9", "external_channels": []}},
    }
    res = client.post("/api/agents/create", json=spec)
    assert res.status_code == 400  # the real builder's cross-validation, surfaced


# --- lifecycle (S8) ---


def test_patch_enabled_toggles_and_preserves_comments(client, tmp_world):
    registry, _ = tmp_world
    res = client.patch("/api/agents/acme/enabled", json={"enabled": False})
    assert res.status_code == 200
    entries = {e.id: e.enabled for e in load_registry(registry)}
    assert entries == {"default": True, "acme": False}
    assert "# Agent registry — comments must survive edits." in registry.read_text()
    # And back on.
    client.patch("/api/agents/acme/enabled", json={"enabled": True})
    assert {e.id: e.enabled for e in load_registry(registry)}["acme"] is True


def test_patch_enabled_unknown_agent_404(client):
    assert client.patch("/api/agents/ghost/enabled", json={"enabled": False}).status_code == 404


def test_delete_removes_entry_keeps_profile_dir(client, tmp_world):
    registry, profiles = tmp_world
    (profiles / "acme").mkdir()
    (profiles / "acme" / "profile.yaml").write_text("name: acme\n", encoding="utf-8")
    res = client.delete("/api/agents/acme")
    assert res.status_code == 200
    assert {e.id for e in load_registry(registry)} == {"default"}
    assert (profiles / "acme" / "profile.yaml").exists()  # archive kept


def test_delete_default_is_refused(client, tmp_world):
    registry, _ = tmp_world
    assert client.delete("/api/agents/default").status_code == 400
    assert {e.id for e in load_registry(registry)} == {"default", "acme"}


def test_delete_unknown_agent_404(client):
    assert client.delete("/api/agents/ghost").status_code == 404


def test_patch_enabled_reports_effective_state(client, tmp_world):
    # 'acme' has no profile dir in tmp_world → the profile gate vetoes the resume; the
    # response must say so instead of pretending the agent is running again.
    res = client.patch("/api/agents/acme/enabled", json={"enabled": True})
    assert res.status_code == 200
    assert res.json() == {"agent_id": "acme", "enabled": True, "effective_enabled": False}
    # An agent whose profile is enabled resumes for real.
    client.post("/api/agents/create", json=_GOOD_SPEC)
    res = client.patch("/api/agents/hr-team/enabled", json={"enabled": True})
    assert res.json()["effective_enabled"] is True


def test_append_registry_no_trailing_newline_stays_valid(tmp_world):
    registry, _ = tmp_world
    registry.write_text(registry.read_text(encoding="utf-8").rstrip("\n"), encoding="utf-8")
    registry_edit.append_registry(registry, "newbie")
    assert {e.id for e in load_registry(registry)} == {"default", "acme", "newbie"}


def test_append_registry_incompatible_indent_raises_and_keeps_file(tmp_world):
    registry, _ = tmp_world
    # Valid YAML but 0-indent list items — the 2-space appended block would produce a
    # mixed-indent sequence. The append must raise and leave the file byte-unchanged
    # (validate-before-replace), never persist a registry no agent can load.
    weird = "agents:\n- id: default\n  enabled: true\n"
    registry.write_text(weird, encoding="utf-8")
    import yaml

    with pytest.raises((RuntimeError, yaml.YAMLError)):
        registry_edit.append_registry(registry, "newbie")
    assert registry.read_text(encoding="utf-8") == weird
    assert {e.id for e in load_registry(registry)} == {"default"}


def test_registry_edit_failure_leaves_file_untouched(tmp_world):
    registry, _ = tmp_world
    before = registry.read_text(encoding="utf-8")
    with pytest.raises(registry_edit.UnknownRegistryAgentError):
        registry_edit.set_registry_enabled(registry, "ghost", False)
    assert registry.read_text(encoding="utf-8") == before


# --- integration health (S9) ---


def _isolate_health(monkeypatch):
    """Fresh cache + no real `gh` subprocess (keeps the suite offline/deterministic)."""
    from src.server import integration_health

    monkeypatch.setattr(integration_health, "_cache", {"at": 0.0, "payload": None})
    monkeypatch.setattr(
        integration_health,
        "_gh_check",
        lambda: integration_health._check("github", "GitHub (gh CLI)", True, "stubbed", "n/a"),
    )
    return integration_health


def test_health_reports_checks_without_secret_values(client, monkeypatch):
    secret = "xoxc-super-secret-value-123"
    monkeypatch.setenv("SLACK_XOXC_TOKEN", secret)
    _isolate_health(monkeypatch)
    res = client.get("/api/health/integrations")
    assert res.status_code == 200
    body = res.json()
    ids = {c["id"] for c in body["checks"]}
    assert {"openrouter", "atlassian", "slack", "github", "gws", "jira_mcp"} <= ids
    assert secret not in res.text  # presence only — never the value
    for check in body["checks"]:
        assert set(check) == {"id", "label", "ok", "detail", "hint"}


def test_health_is_cached_between_calls(client, monkeypatch):
    integration_health = _isolate_health(monkeypatch)
    calls = {"n": 0}
    real = integration_health._run_checks

    def _counting():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(integration_health, "_run_checks", _counting)
    client.get("/api/health/integrations")
    client.get("/api/health/integrations")
    assert calls["n"] == 1
