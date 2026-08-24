"""Per-agent model roles and the advisor toggle, as read from `profile.yaml`.

Both keys already reached `Settings` through `loader_mapping.py`, but nothing pinned
that path: a rename or a dropped `_put` line would have surfaced as a fleet running
every role on the expensive model (and no second opinion) with no error anywhere —
the silent-cost failure mode `_d_role_models` exists to prevent, one layer up.

These tests use `load_profile(profiles_dir=...)` against a temp profile so they read
the real yaml→Settings path, not a hand-built dict.
"""

from __future__ import annotations

import pytest

from my_crew.profile.loader import load_profile


def _write_profile(tmp_path, body: str, agent_id: str = "tester"):
    d = tmp_path / agent_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "profile.yaml").write_text(body, encoding="utf-8")
    return tmp_path


def _load(tmp_path, body: str):
    base = _write_profile(tmp_path, body)
    return load_profile("tester", profiles_dir=base).settings


class TestRoleModelsFromProfileYaml:
    def test_a_yaml_mapping_reaches_settings_including_the_advisor_role(self, tmp_path):
        s = _load(
            tmp_path,
            "name: Tester\n"
            "role_models:\n"
            "  content: vendor/writer\n"
            "  advisor: vendor/cheap-advisor\n",
        )
        assert dict(s.role_models) == {
            "content": "vendor/writer",
            "advisor": "vendor/cheap-advisor",
        }

    def test_the_advisor_role_resolves_to_its_own_chain_not_the_fleet_model(self, tmp_path):
        s = _load(
            tmp_path,
            "model: fleet/model\nrole_models:\n  advisor: vendor/cheap-advisor\n",
        )
        assert s.model_for_role("advisor") == ("vendor/cheap-advisor", "fleet/model")
        assert s.model_for_role("content") == ("fleet/model",)

    def test_yaml_beats_the_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENROUTER_ROLE_MODELS", "content=env/model")
        s = _load(tmp_path, "role_models:\n  content: yaml/model\n")
        assert dict(s.role_models) == {"content": "yaml/model"}

    def test_the_env_is_used_only_when_the_yaml_key_is_absent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENROUTER_ROLE_MODELS", "review=env/cheap,advisor=env/advisor")
        s = _load(tmp_path, "name: Tester\n")
        assert dict(s.role_models) == {"review": "env/cheap", "advisor": "env/advisor"}

    def test_a_typod_role_in_a_profile_fails_the_load_instead_of_billing_silently(
        self, tmp_path
    ):
        with pytest.raises(ValueError, match="unknown role_models key"):
            _load(tmp_path, "role_models:\n  contnet: vendor/writer\n")


class TestAdvisorEnabledFromProfileYaml:
    def test_it_is_off_unless_the_profile_or_env_turns_it_on(self, tmp_path):
        assert _load(tmp_path, "name: Tester\n").advisor_enabled is False

    def test_the_runtime_block_turns_it_on(self, tmp_path):
        assert _load(tmp_path, "runtime:\n  advisor_enabled: true\n").advisor_enabled is True

    def test_an_explicit_false_in_yaml_beats_an_env_that_says_on(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ADVISOR_ENABLED", "true")
        s = _load(tmp_path, "runtime:\n  advisor_enabled: false\n")
        assert s.advisor_enabled is False

    def test_the_env_turns_it_on_when_the_profile_is_silent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ADVISOR_ENABLED", "true")
        assert _load(tmp_path, "name: Tester\n").advisor_enabled is True
