"""v88 P4: GET/PATCH /api/agents/{id}/profile-settings, POST .../band, GET
model-catalog. Offline.

Load-bearing:
- PATCH writes through `profile_patch` (comment-preserving ruamel round-trip) — a name
  change must not disturb any other comment/sibling key (diff-based, mirrors the P2 test).
- Each of name/model/model_chain/budget_monthly_usd/schedule is independently
  patchable (subset body) and independently validated (bad value → 400, nothing written).
- Band is a BandStore side-effect, not a profile.yaml write — invalid band → 400
  (ValueError from BandStore.set is caught, not a 500).
- model-catalog reads `config/model_prices.yaml` via `model_pricing.load_prices`
  (never hardcoded, never network) and degrades to `{"models": []}` when unpriced/missing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _client():
    from my_crew.server.app import create_app

    return TestClient(create_app())


@pytest.fixture
def agent_profiles(tmp_path, monkeypatch):
    """A throwaway profiles/ tree + isolated band-store DB + isolated model-prices file."""
    profiles = tmp_path / "profiles"
    (profiles / "acme").mkdir(parents=True)
    (profiles / "acme" / "profile.yaml").write_text(
        "# hand-written comment — must survive every patch below\n"
        "name: acme\n"
        "domain: pm\n"
        "weird_handwritten_key: xin chào thế giới\n"
        "# model comment\n"
        "# model: leave-out-to-follow-fleet\n"
        "budget:\n"
        "  monthly_usd: 50   # inline comment\n"
        "  warn_ratio: 0.8\n"
        "safety:\n"
        "  dry_run: true\n"
        "schedule:\n"
        "  weekly_report: '0 9 * * 1'\n",
        encoding="utf-8",
    )
    (profiles / "bare").mkdir(parents=True)
    (profiles / "bare" / "profile.yaml").write_text("name: bare\ndomain: pm\n", encoding="utf-8")

    monkeypatch.setattr("my_crew.profile.loader._PROFILES_DIR", profiles)
    monkeypatch.setattr("my_crew.server.profile_patch.MY_CREW_HOME", tmp_path)

    from my_crew.runtime import band_store

    band_db = tmp_path / "agent_bands.sqlite3"
    monkeypatch.setattr(band_store, "_db_path", lambda: band_db)

    return {"profiles": profiles, "tmp_path": tmp_path}


@pytest.fixture
def model_prices_file(tmp_path, monkeypatch):
    prices = tmp_path / "model_prices.yaml"
    prices.write_text(
        "models:\n"
        "  \"vendor/zeta\":\n"
        "    input_per_1m: 1.0\n"
        "    output_per_1m: 2.0\n"
        "  \"vendor/alpha\":\n"
        "    input_per_1m: 0.5\n"
        "    output_per_1m: 1.5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("my_crew.llm.model_pricing.DEFAULT_PRICES_PATH", prices)
    return prices


def _profile_text(agent_profiles, agent_id="acme"):
    return (agent_profiles["profiles"] / agent_id / "profile.yaml").read_text(encoding="utf-8")


# --- GET profile-settings -------------------------------------------------


def test_get_profile_settings_returns_raw_values(agent_profiles):
    r = _client().get("/api/agents/acme/profile-settings")
    assert r.status_code == 200
    body = r.json()
    assert body["agent_id"] == "acme"
    assert body["name"] == "acme"
    assert body["model"] is None
    assert body["model_chain"] == []
    assert body["budget_monthly_usd"] == 50
    assert body["schedule"] == {"weekly_report": "0 9 * * 1"}


def test_get_profile_settings_absent_fields_degrade_cleanly(agent_profiles):
    r = _client().get("/api/agents/bare/profile-settings")
    assert r.status_code == 200
    body = r.json()
    assert body["model"] is None
    assert body["model_chain"] == []
    assert body["budget_monthly_usd"] is None
    assert body["schedule"] == {}


def test_get_profile_settings_unknown_agent_404(agent_profiles):
    r = _client().get("/api/agents/nope/profile-settings")
    assert r.status_code == 404


def test_get_profile_settings_invalid_agent_id_400(agent_profiles):
    r = _client().get("/api/agents/BAD-CAPS/profile-settings")
    assert r.status_code == 400


# --- PATCH profile-settings: happy path per field --------------------------


def test_patch_name_happy_path_preserves_comments(agent_profiles):
    before = _profile_text(agent_profiles)
    r = _client().patch("/api/agents/acme/profile-settings", json={"name": "Acme Renamed"})
    assert r.status_code == 200
    assert r.json() == {"agent_id": "acme", "needs_restart": False}

    after = _profile_text(agent_profiles)
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    assert len(before_lines) == len(after_lines)
    diff = [(b, a) for b, a in zip(before_lines, after_lines, strict=True) if b != a]
    assert diff == [("name: acme", "name: Acme Renamed")]
    assert "# hand-written comment — must survive every patch below" in after
    assert "weird_handwritten_key: xin chào thế giới" in after


def test_patch_model_happy_path(agent_profiles):
    r = _client().patch(
        "/api/agents/acme/profile-settings", json={"model": "vendor/new-model"}
    )
    assert r.status_code == 200
    text = _profile_text(agent_profiles)
    assert "model: vendor/new-model" in text
    # sibling comment untouched
    assert "weird_handwritten_key: xin chào thế giới" in text


def test_patch_model_empty_string_clears_override(agent_profiles):
    _client().patch("/api/agents/acme/profile-settings", json={"model": "vendor/x"})
    r = _client().patch("/api/agents/acme/profile-settings", json={"model": ""})
    assert r.status_code == 200
    text = _profile_text(agent_profiles)
    assert "model: ''" in text or "model:" in text


def test_patch_model_chain_happy_path(agent_profiles):
    r = _client().patch(
        "/api/agents/acme/profile-settings",
        json={"model_chain": ["vendor/primary", "vendor/fallback"]},
    )
    assert r.status_code == 200
    get_r = _client().get("/api/agents/acme/profile-settings")
    assert get_r.json()["model_chain"] == ["vendor/primary", "vendor/fallback"]


def test_patch_model_chain_empty_list_is_valid(agent_profiles):
    r = _client().patch("/api/agents/acme/profile-settings", json={"model_chain": []})
    assert r.status_code == 200
    get_r = _client().get("/api/agents/acme/profile-settings")
    assert get_r.json()["model_chain"] == []


def test_patch_budget_happy_path_preserves_warn_ratio(agent_profiles):
    r = _client().patch(
        "/api/agents/acme/profile-settings", json={"budget_monthly_usd": 120}
    )
    assert r.status_code == 200
    text = _profile_text(agent_profiles)
    assert "monthly_usd: 120" in text
    assert "warn_ratio: 0.8" in text  # sibling leaf untouched


def test_patch_schedule_happy_path_full_replace(agent_profiles):
    r = _client().patch(
        "/api/agents/acme/profile-settings",
        json={"schedule": {"daily_standup": "0 8 * * *"}},
    )
    assert r.status_code == 200
    get_r = _client().get("/api/agents/acme/profile-settings")
    # whole-block replace: the old weekly_report kind is gone, only the submitted kind remains
    assert get_r.json()["schedule"] == {"daily_standup": "0 8 * * *"}


def test_patch_multiple_fields_at_once(agent_profiles):
    r = _client().patch(
        "/api/agents/bare/profile-settings",
        json={"name": "Bare Two", "budget_monthly_usd": 10},
    )
    assert r.status_code == 200
    get_r = _client().get("/api/agents/bare/profile-settings")
    body = get_r.json()
    assert body["name"] == "Bare Two"
    assert body["budget_monthly_usd"] == 10


# --- PATCH profile-settings: 400 cases --------------------------------------


def test_patch_empty_name_400(agent_profiles):
    r = _client().patch("/api/agents/acme/profile-settings", json={"name": "   "})
    assert r.status_code == 400
    assert _profile_text(agent_profiles) == _profile_text(agent_profiles)  # unchanged sanity


def test_patch_model_chain_non_list_400(agent_profiles):
    r = _client().patch(
        "/api/agents/acme/profile-settings", json={"model_chain": "not-a-list"}
    )
    assert r.status_code in (400, 422)


def test_patch_model_chain_with_empty_string_entry_400(agent_profiles):
    r = _client().patch(
        "/api/agents/acme/profile-settings", json={"model_chain": ["vendor/ok", "  "]}
    )
    assert r.status_code == 400


def test_patch_budget_negative_400(agent_profiles):
    r = _client().patch(
        "/api/agents/acme/profile-settings", json={"budget_monthly_usd": -5}
    )
    assert r.status_code == 400


def test_patch_budget_non_number_400(agent_profiles):
    r = _client().patch(
        "/api/agents/acme/profile-settings", json={"budget_monthly_usd": "fifty"}
    )
    assert r.status_code in (400, 422)


def test_patch_schedule_invalid_cron_400(agent_profiles):
    before = _profile_text(agent_profiles)
    r = _client().patch(
        "/api/agents/acme/profile-settings",
        json={"schedule": {"weekly_report": "not a cron"}},
    )
    assert r.status_code == 400
    assert _profile_text(agent_profiles) == before  # rejected patch touches nothing


def test_patch_schedule_non_mapping_400(agent_profiles):
    r = _client().patch(
        "/api/agents/acme/profile-settings", json={"schedule": ["not", "a", "map"]}
    )
    assert r.status_code in (400, 422)


def test_patch_unknown_agent_404(agent_profiles):
    r = _client().patch("/api/agents/nope/profile-settings", json={"name": "x"})
    assert r.status_code == 404


def test_patch_invalid_agent_id_400(agent_profiles):
    r = _client().patch("/api/agents/BAD-CAPS/profile-settings", json={"name": "x"})
    assert r.status_code == 400


def test_patch_empty_body_is_a_noop_200(agent_profiles):
    before = _profile_text(agent_profiles)
    r = _client().patch("/api/agents/acme/profile-settings", json={})
    assert r.status_code == 200
    assert _profile_text(agent_profiles) == before


# --- GET band ------------------------------------------------------------------


def test_get_band_defaults_to_normal_when_never_set(agent_profiles):
    r = _client().get("/api/agents/acme/band")
    assert r.status_code == 200
    assert r.json() == {"agent_id": "acme", "band": "normal"}


def test_get_band_reflects_a_prior_set(agent_profiles):
    _client().post("/api/agents/acme/band", json={"band": "trusted"})
    r = _client().get("/api/agents/acme/band")
    assert r.status_code == 200
    assert r.json() == {"agent_id": "acme", "band": "trusted"}


def test_get_band_unknown_agent_404(agent_profiles):
    r = _client().get("/api/agents/nope/band")
    assert r.status_code == 404


def test_get_band_invalid_agent_id_400(agent_profiles):
    r = _client().get("/api/agents/BAD-CAPS/band")
    assert r.status_code == 400


# --- POST band ---------------------------------------------------------------


def test_set_band_happy_path(agent_profiles):
    r = _client().post(
        "/api/agents/acme/band", json={"band": "trusted", "reason": "CEO test"}
    )
    assert r.status_code == 200
    assert r.json() == {"agent_id": "acme", "band": "trusted"}

    from my_crew.runtime.band_store import BandStore

    store = BandStore(db_path=agent_profiles["tmp_path"] / "agent_bands.sqlite3")
    try:
        assert store.get("acme") == "trusted"
    finally:
        store.close()


def test_set_band_defaults_reason_when_omitted(agent_profiles):
    r = _client().post("/api/agents/acme/band", json={"band": "normal"})
    assert r.status_code == 200

    from my_crew.runtime.band_store import BandStore

    store = BandStore(db_path=agent_profiles["tmp_path"] / "agent_bands.sqlite3")
    try:
        row = store._conn.execute(
            "SELECT reason, changed_by FROM agent_bands WHERE agent_id=?", ("acme",)
        ).fetchone()
        assert row[0]  # non-empty default reason
        assert row[1] == "ceo"
    finally:
        store.close()


def test_set_band_invalid_value_400(agent_profiles):
    r = _client().post("/api/agents/acme/band", json={"band": "godmode"})
    assert r.status_code == 400


def test_set_band_does_not_touch_profile_yaml(agent_profiles):
    before = _profile_text(agent_profiles)
    _client().post("/api/agents/acme/band", json={"band": "trusted"})
    assert _profile_text(agent_profiles) == before


def test_set_band_unknown_agent_404(agent_profiles):
    r = _client().post("/api/agents/nope/band", json={"band": "trusted"})
    assert r.status_code == 404


def test_set_band_invalid_agent_id_400(agent_profiles):
    r = _client().post("/api/agents/BAD-CAPS/band", json={"band": "trusted"})
    assert r.status_code == 400


# --- GET model-catalog ---------------------------------------------------------


def test_model_catalog_returns_sorted_ids(model_prices_file):
    r = _client().get("/api/agents/model-catalog")
    assert r.status_code == 200
    assert r.json() == {"models": ["vendor/alpha", "vendor/zeta"]}


def test_model_catalog_missing_file_degrades_to_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "my_crew.llm.model_pricing.DEFAULT_PRICES_PATH", tmp_path / "no-such-file.yaml"
    )
    r = _client().get("/api/agents/model-catalog")
    assert r.status_code == 200
    assert r.json() == {"models": []}
