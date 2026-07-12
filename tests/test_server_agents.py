"""M2-P6 Slice 1: read-only agent routes via FastAPI TestClient (fully offline).

Monkeypatches load_registry / load_profile / read_last_run_event on agent_views so no
real profile/registry files are read. Budget + pending-approvals use a REAL Settings
pinned to tmp_path (BudgetTracker + ActionGateway read tmp files), so the status route
exercises the real store readers with no network and no graph build.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from src.server import agent_views
from src.server.app import create_app


def _profile(settings, *, name="Acme", enabled=True, external=frozenset(), domain="pm"):
    # Mirror LoadedProfile: `domain` always exists (defaults to "pm") — list_agents reads it.
    config = type("Cfg", (), {"slack_external_channels": external})()
    return type(
        "LP",
        (),
        {
            "name": name, "enabled": enabled, "settings": settings,
            "config": config, "domain": domain,
        },
    )()


def _patch(monkeypatch, *, ids_enabled, profiles, last_runs):
    """ids_enabled: list[(id, registry_enabled)]; profiles: {id: LP}; last_runs: {id: dict|None}."""
    from src.runtime.registry import RegistryEntry

    entries = tuple(RegistryEntry(i, en) for i, en in ids_enabled)
    monkeypatch.setattr(agent_views, "load_registry", lambda: entries)
    monkeypatch.setattr(agent_views, "load_profile", lambda i, **k: profiles[i])
    monkeypatch.setattr(agent_views, "read_last_run_event", lambda i: last_runs.get(i))


def _client() -> TestClient:
    return TestClient(create_app())


def test_list_agents_one_entry_per_registry_agent(monkeypatch, settings_factory):
    s = settings_factory()
    _patch(
        monkeypatch,
        ids_enabled=[("acme", True), ("beta", True)],
        profiles={"acme": _profile(s, name="Acme"), "beta": _profile(s, name="Beta")},
        last_runs={
            "acme": {"kind": "daily", "status": "delivered", "delivered": True},
            "beta": None,
        },
    )
    r = _client().get("/api/agents")
    assert r.status_code == 200
    body = r.json()
    assert [a["id"] for a in body] == ["acme", "beta"]
    assert body[0]["name"] == "Acme" and body[0]["enabled"] is True
    assert body[0]["last_run"]["status"] == "delivered"
    assert body[1]["last_run"] is None
    # effective trust mode rides the list payload (fixture settings pin "guarded")
    assert body[0]["trust_mode"] == "guarded"


def test_list_agents_exposes_report_kinds_per_pack(monkeypatch, settings_factory):
    # v10 M25 (red-team F4): the list carries the report kinds this agent's OWN pack serves,
    # so the web Trigger form offers the right set (not a hardcoded PM four). A pm-domain agent
    # gets pm's kinds; an unknown/broken domain degrades to [] without 500-ing the list.
    s = settings_factory()
    pm = _profile(s, name="PM", domain="pm")
    broken = _profile(s, name="Broken", domain="no-such-domain")
    _patch(
        monkeypatch,
        ids_enabled=[("pm", True), ("broken", True)],
        profiles={"pm": pm, "broken": broken},
        last_runs={"pm": None, "broken": None},
    )
    body = _client().get("/api/agents").json()
    by_id = {a["id"]: a for a in body}
    # pm pack serves at least the canonical daily report kind
    assert "daily" in by_id["pm"]["report_kinds"]
    # an unknown domain never raises here — it just yields no kinds
    assert by_id["broken"]["report_kinds"] == []


def test_enabled_is_registry_and_profile_and(monkeypatch, settings_factory):
    s = settings_factory()
    # registry-enabled but profile-disabled ⇒ enabled false
    _patch(
        monkeypatch,
        ids_enabled=[("a", True)],
        profiles={"a": _profile(s, enabled=False)},
        last_runs={"a": None},
    )
    body = _client().get("/api/agents").json()
    assert body[0]["enabled"] is False


def test_status_includes_budget_and_pending(monkeypatch, settings_factory, tmp_path):
    s = settings_factory()  # data_dir = tmp_path
    # seed a budget file the BudgetTracker will read
    bdir = tmp_path / "budget"
    bdir.mkdir(parents=True, exist_ok=True)
    from datetime import UTC, datetime

    month = datetime.now(UTC).strftime("%Y-%m")
    (bdir / f"budget-{month}.json").write_text(
        json.dumps({"month": month, "total_usd": 12.5}), encoding="utf-8"
    )
    # seed a pending Lớp B approval in the real approval store under tmp
    from src.actions.action_gateway import ActionGateway

    gw = ActionGateway(s, external_channels=frozenset())
    gw.execute({"type": "gh_cli", "argv": ["pr", "merge", "1"]}, handler=lambda a: "x")

    _patch(
        monkeypatch,
        ids_enabled=[("acme", True)],
        profiles={"acme": _profile(s)},
        last_runs={"acme": {"kind": "daily", "status": "delivered"}},
    )
    body = _client().get("/api/agents/acme/status").json()
    assert body["budget"]["spent"] == 12.5
    assert body["budget"]["cap"] == 50.0
    assert abs(body["budget"]["ratio"] - 0.25) < 1e-9
    assert body["pending_approvals"] == 1
    assert body["trust_mode"] == "guarded"


def test_status_unknown_id_404(monkeypatch, settings_factory):
    s = settings_factory()
    _patch(monkeypatch, ids_enabled=[("acme", True)], profiles={"acme": _profile(s)}, last_runs={})
    r = _client().get("/api/agents/ghost/status")
    assert r.status_code == 404


def test_list_survives_a_broken_profile(monkeypatch, settings_factory):
    # One agent's profile fails to load → that entry degrades, the list still serves
    # the healthy agent (mirrors the CLI run_list resilience, not a 500).
    s = settings_factory()
    from src.runtime.registry import RegistryEntry

    entries = (RegistryEntry("good", True), RegistryEntry("broken", True))
    monkeypatch.setattr(agent_views, "load_registry", lambda: entries)
    monkeypatch.setattr(agent_views, "read_last_run_event", lambda i: None)

    def _load(i, **k):
        if i == "broken":
            raise RuntimeError("bad profile.yaml")
        return _profile(s, name="Good")

    monkeypatch.setattr(agent_views, "load_profile", _load)
    r = _client().get("/api/agents")
    assert r.status_code == 200
    body = {a["id"]: a for a in r.json()}
    assert body["good"]["name"] == "Good"
    assert body["broken"]["enabled"] is False
    assert body["broken"]["name"].startswith("<error:")
    # a broken profile must surface the conservative mode, not crash the field
    assert body["broken"]["trust_mode"] == "guarded"


def test_list_no_api_key_needed(monkeypatch, settings_factory):
    # graph is never built, so a no-key settings still serves the list.
    s = settings_factory(api_key=None)
    _patch(
        monkeypatch,
        ids_enabled=[("acme", True)],
        profiles={"acme": _profile(s)},
        last_runs={"acme": None},
    )
    assert _client().get("/api/agents").status_code == 200
