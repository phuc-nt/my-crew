"""v87 P2: GET/PATCH /api/agents/{id}/safety — dry-run visibility + toggle. Offline.

Load-bearing:
- GET returns the SAME effective value `load_profile` (the worker's resolution) would
  compute, not a re-derived one.
- PATCH writes through `profile_patch` (comment-preserving) and returns
  `needs_restart: false` — profile.yaml is re-read fresh by both the scheduler tick and
  each spawned worker subprocess (see routes_agent_safety.py docstring for the evidence),
  so no restart is required, unlike the `.env`-key writes in routes_connections.py.
- 404 unknown agent (GET + PATCH); 422 malformed body (FastAPI's own validation).
- The write is idempotent and does not disturb any other profile.yaml content.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _client():
    from my_crew.server.app import create_app

    return TestClient(create_app())


@pytest.fixture
def agent_profiles(tmp_path, monkeypatch):
    """A throwaway profiles/ tree with two agents: one explicit dry_run=true override,
    one with no safety block at all (inherits the fleet default)."""
    profiles = tmp_path / "profiles"
    (profiles / "acme").mkdir(parents=True)
    (profiles / "acme" / "profile.yaml").write_text(
        "# hand-written comment\n"
        "name: acme\n"
        "domain: pm\n"
        "safety:\n"
        "  trust_mode: autonomous\n"
        "  dry_run: true\n",
        encoding="utf-8",
    )
    (profiles / "bare").mkdir(parents=True)
    (profiles / "bare" / "profile.yaml").write_text("name: bare\ndomain: pm\n", encoding="utf-8")

    monkeypatch.setattr("my_crew.profile.loader._PROFILES_DIR", profiles)
    monkeypatch.setattr("my_crew.server.profile_patch.MY_CREW_HOME", tmp_path)
    # load_profile reads .env via load_dotenv(MY_CREW_HOME / ".env") — point it at an
    # empty throwaway file so it never touches the real repo .env.
    monkeypatch.setattr("my_crew.profile.loader.MY_CREW_HOME", tmp_path)
    return {"profiles": profiles}


def test_get_returns_effective_dry_run_from_profile_override(agent_profiles):
    r = _client().get("/api/agents/acme/safety")
    assert r.status_code == 200
    body = r.json()
    assert body == {"agent_id": "acme", "dry_run": True, "dry_run_source": "profile"}


def test_get_returns_fleet_default_when_no_override(agent_profiles):
    r = _client().get("/api/agents/bare/safety")
    assert r.status_code == 200
    body = r.json()
    # P1 default is dry_run=True absent any profile key / env var.
    assert body == {"agent_id": "bare", "dry_run": True, "dry_run_source": "fleet"}


def test_get_unknown_agent_404(agent_profiles):
    r = _client().get("/api/agents/nope/safety")
    assert r.status_code == 404


def test_get_invalid_agent_id_400(agent_profiles):
    r = _client().get("/api/agents/BAD-ID-CAPS/safety")
    assert r.status_code == 400


def test_patch_flips_dry_run_and_reports_no_restart_needed(agent_profiles):
    r = _client().patch("/api/agents/acme/safety", json={"dry_run": False})
    assert r.status_code == 200
    assert r.json() == {"agent_id": "acme", "dry_run": False, "needs_restart": False}

    # The write took effect — a fresh GET (== a fresh load_profile, same as the worker
    # would do on its next dispatch) sees it.
    r2 = _client().get("/api/agents/acme/safety")
    assert r2.json()["dry_run"] is False
    assert r2.json()["dry_run_source"] == "profile"


def test_patch_creates_safety_block_for_bare_agent(agent_profiles):
    r = _client().patch("/api/agents/bare/safety", json={"dry_run": False})
    assert r.status_code == 200
    assert r.json()["dry_run"] is False
    text = (agent_profiles["profiles"] / "bare" / "profile.yaml").read_text(encoding="utf-8")
    assert "safety:" in text and "dry_run: false" in text
    assert "name: bare" in text  # untouched


def test_patch_preserves_comments_and_sibling_keys(agent_profiles):
    _client().patch("/api/agents/acme/safety", json={"dry_run": False})
    text = (agent_profiles["profiles"] / "acme" / "profile.yaml").read_text(encoding="utf-8")
    assert "# hand-written comment" in text
    assert "trust_mode: autonomous" in text
    assert "dry_run: false" in text


def test_patch_unknown_agent_404(agent_profiles):
    r = _client().patch("/api/agents/nope/safety", json={"dry_run": False})
    assert r.status_code == 404


def test_patch_invalid_agent_id_400(agent_profiles):
    r = _client().patch("/api/agents/BAD-ID-CAPS/safety", json={"dry_run": False})
    assert r.status_code == 400


def test_patch_malformed_body_422(agent_profiles):
    r = _client().patch("/api/agents/acme/safety", json={"dry_run": "not-a-bool"})
    assert r.status_code == 422


def test_patch_idempotent(agent_profiles):
    first = _client().patch("/api/agents/acme/safety", json={"dry_run": False})
    text1 = (agent_profiles["profiles"] / "acme" / "profile.yaml").read_text(encoding="utf-8")
    second = _client().patch("/api/agents/acme/safety", json={"dry_run": False})
    text2 = (agent_profiles["profiles"] / "acme" / "profile.yaml").read_text(encoding="utf-8")
    assert first.status_code == second.status_code == 200
    assert text1 == text2
