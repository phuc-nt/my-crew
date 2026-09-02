"""The live harness must serve the fleet on the model it DECLARES.

Offline on purpose and outside `tests/fullflow_live/` for the same reason as the settle
predicate guard: that package is all `live`, and a guard that only runs with a key runs
exactly when it is not needed.

What was measured before this guard existed (2026-09-02): `cast.LIVE_MODEL` said haiku,
the seeded home `.env` said haiku, and every transcript said the developer's default
model. Two harness gaps, each silent:

  * `boot()` handed the child `os.environ`, which already carried `OPENROUTER_MODEL`
    from the repo `.env` — `build_settings_from_env()` loads it into the process at
    import time in any test module — and the child's own `.env` load does not override.
  * The per-role models were written as `ROLE_MODEL_<ROLE>=` lines, a key nothing in
    the config reads; the config wants one `OPENROUTER_ROLE_MODELS=role=model,...`.

Neither failed a test; the fleet just ran on a slower model than the suite's timings
were sized for, and the reds it produced were chased as product bugs.
"""

from __future__ import annotations

from my_crew.config.config_builders import build_settings_from_dict
from tests.fullflow.cast import LIVE_MODEL, LIVE_ROLE_MODELS
from tests.fullflow_live.topology import role_models_env, seed_home, serve_env


def test_the_served_fleet_runs_the_declared_model_over_the_developer_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "some-other/model")
    monkeypatch.setenv("OPENROUTER_ROLE_MODELS", "content=some-other/model")

    env = serve_env(tmp_path, port=1, api_key="k")

    assert env["OPENROUTER_MODEL"] == LIVE_MODEL
    assert env["OPENROUTER_ROLE_MODELS"] == role_models_env()


def test_a_case_can_still_pin_another_model_on_purpose(tmp_path):
    env = serve_env(tmp_path, port=1, api_key="k", env_overrides={"OPENROUTER_MODEL": "pin/me"})

    assert env["OPENROUTER_MODEL"] == "pin/me"


def test_role_models_reach_the_config_in_the_form_it_parses():
    """The string handed to the child must round-trip through the real parser to the
    same mapping `cast.py` declares — not a key the config silently ignores."""
    settings = build_settings_from_dict({
        "openrouter_api_key": "k",
        "openrouter_model": LIVE_MODEL,
        "role_models": role_models_env(),
    })

    assert dict(settings.role_models) == LIVE_ROLE_MODELS


def test_the_seeded_home_env_names_role_models_under_the_key_the_config_reads(tmp_path):
    seed_home(tmp_path, api_key="k")
    text = (tmp_path / ".env").read_text(encoding="utf-8")

    assert f"OPENROUTER_MODEL={LIVE_MODEL}" in text
    assert f"OPENROUTER_ROLE_MODELS={role_models_env()}" in text
    assert "ROLE_MODEL_" not in text  # the unread key is gone, not merely duplicated
