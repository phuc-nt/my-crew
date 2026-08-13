"""Three tiers of model configuration: fleet (.env) → agent (profile) → role (per call).

The load-bearing property is that the fleet tier actually reaches every agent. Before
v79 all shipped profiles wrote a literal `model:`, and since a profile value wins over
the env, `OPENROUTER_MODEL` moved nothing — the documented fleet switch was dead. The
first test class is the regression guard for exactly that.

Offline: no key, no network. Role resolution is pure `Settings` arithmetic.
"""

from __future__ import annotations

import pytest

from my_crew.config.config_builders import build_settings_from_dict
from my_crew.config.settings import DEFAULT_MODEL, MODEL_ROLES


def _settings(**over):
    return build_settings_from_dict({"openrouter_model": "fleet/model", **over})


class TestFleetTierReachesEveryAgent:
    def test_a_shipped_profile_declares_no_model_so_the_env_governs_it(self, tmp_path):
        """The shipped profiles must not pin a model, or the fleet switch is a no-op."""
        import os
        from pathlib import Path

        from my_crew.profile.loader import load_profile

        repo_profiles = Path(__file__).resolve().parent.parent / "profiles"
        prior = os.environ.get("OPENROUTER_MODEL")
        os.environ["OPENROUTER_MODEL"] = "sentinel/from-env"
        try:
            for profile_dir in sorted(repo_profiles.iterdir()):
                if not (profile_dir / "profile.yaml").exists():
                    continue
                resolved = load_profile(profile_dir.name).settings.openrouter_model
                assert resolved == "sentinel/from-env", (
                    f"profile {profile_dir.name!r} pins a model, so a fleet-wide swap "
                    f"would silently skip it (resolved {resolved!r})"
                )
        finally:
            if prior is None:
                os.environ.pop("OPENROUTER_MODEL", None)
            else:
                os.environ["OPENROUTER_MODEL"] = prior

    def test_absent_everywhere_falls_back_to_the_compiled_default(self):
        assert build_settings_from_dict({}).openrouter_model == DEFAULT_MODEL


class TestRoleTier:
    def test_an_unconfigured_role_is_exactly_the_fleet_chain(self):
        s = _settings()
        assert s.model_for_role("review") == s.effective_model_chain()

    def test_an_unknown_role_name_is_not_an_error_it_just_has_no_override(self):
        """Call sites may name a role before anyone configures a model for it."""
        s = _settings(role_models={"review": "cheap/model"})
        assert s.model_for_role("never-configured") == ("fleet/model",)

    def test_an_override_leads_but_keeps_the_fleet_model_as_a_fallback_tail(self):
        """A cheap model is the kind that gets rate-limited — it must not lose fallback."""
        s = _settings(role_models={"review": "cheap/model"})
        assert s.model_for_role("review") == ("cheap/model", "fleet/model")

    def test_an_override_is_not_duplicated_when_it_already_sits_in_the_chain(self):
        s = _settings(
            model_chain=["cheap/model", "fleet/model"],
            role_models={"review": "cheap/model"},
        )
        assert s.model_for_role("review") == ("cheap/model", "fleet/model")

    def test_the_override_tail_is_the_declared_chain_not_just_the_single_model(self):
        s = _settings(
            model_chain=["primary/a", "backup/b"],
            role_models={"util": "cheap/c"},
        )
        assert s.model_for_role("util") == ("cheap/c", "primary/a", "backup/b")

    def test_a_role_without_an_override_is_untouched_by_another_roles_override(self):
        s = _settings(role_models={"review": "cheap/model"})
        assert s.model_for_role("content") == ("fleet/model",)


class TestRoleModelsParsing:
    def test_absent_means_every_role_runs_the_fleet_model(self):
        assert _settings().role_models == ()

    def test_an_env_style_comma_string_parses(self):
        s = _settings(role_models="review=cheap/a,util=cheap/b")
        assert s.role_models == (("review", "cheap/a"), ("util", "cheap/b"))

    def test_a_yaml_mapping_parses(self):
        s = _settings(role_models={"aggregate": "cheap/a"})
        assert s.role_models == (("aggregate", "cheap/a"),)

    def test_a_typod_role_name_fails_at_load_not_silently_at_bill_time(self):
        """Ignoring an unknown role would show the fleet bill and no error."""
        with pytest.raises(ValueError, match="unknown role_models key"):
            _settings(role_models={"reviewww": "cheap/a"})

    def test_a_duplicate_role_fails_rather_than_letting_last_wins_decide_quietly(self):
        with pytest.raises(ValueError, match="twice"):
            _settings(role_models="review=a/1,review=b/2")

    def test_a_malformed_entry_fails(self):
        with pytest.raises(ValueError, match="role=model"):
            _settings(role_models="review-cheap/a")

    def test_a_non_string_model_fails_so_an_unquoted_yaml_scalar_cannot_slip_through(self):
        with pytest.raises(ValueError, match="model name string"):
            _settings(role_models={"review": 2.5})

    def test_every_declared_role_name_is_accepted(self):
        for role in MODEL_ROLES:
            assert _settings(role_models={role: "cheap/a"}).role_models == (
                (role, "cheap/a"),
            )


class TestClientHonorsTheRole:
    def _client(self, settings, seen):
        from my_crew.llm.client import LlmClient

        client = LlmClient(settings)

        class _Resp:
            usage = {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.0}
            choices = [
                type("C", (), {"message": type("M", (), {"content": "ok"})()})()
            ]

        def _fake_call(messages, model_name):
            seen.append(model_name)
            return _Resp()

        client._call_with_retry = _fake_call  # type: ignore[method-assign]
        return client

    def test_a_role_call_uses_the_roles_model(self):
        seen: list[str] = []
        settings = _settings(role_models={"review": "cheap/model"})
        self._client(settings, seen).complete([{"role": "user", "content": "x"}],
                                              role="review")
        assert seen == ["cheap/model"]

    def test_an_untagged_call_still_uses_the_fleet_model(self):
        seen: list[str] = []
        settings = _settings(role_models={"review": "cheap/model"})
        self._client(settings, seen).complete([{"role": "user", "content": "x"}])
        assert seen == ["fleet/model"]

    def test_an_explicit_model_still_wins_over_a_role(self):
        seen: list[str] = []
        settings = _settings(role_models={"review": "cheap/model"})
        self._client(settings, seen).complete(
            [{"role": "user", "content": "x"}], model="pinned/model", role="review"
        )
        assert seen == ["pinned/model"]


class TestTheAgentlessLaneStillSeesTierOneAndThree:
    """Coordinator decompose/amend and CEO room chat build settings from env, not a
    profile, because no agent runs them — there is no `agent_id` to load. That lane
    must still honour the fleet switch and the role overrides; only tier 2 (per-agent)
    is legitimately absent. Without this, a fleet swap would move the agents and leave
    decompose/amend on the old model.
    """

    def test_env_settings_carry_the_fleet_model_and_the_role_overrides(self, monkeypatch):
        from my_crew.config.config_builders import build_settings_from_env

        monkeypatch.setenv("OPENROUTER_MODEL", "sentinel/fleet")
        monkeypatch.setenv("OPENROUTER_ROLE_MODELS", "plan=sentinel/cheap")
        settings = build_settings_from_env()
        assert settings.openrouter_model == "sentinel/fleet"
        assert settings.model_for_role("plan") == ("sentinel/cheap", "sentinel/fleet")
        assert settings.model_for_role("content") == ("sentinel/fleet",)


class TestSecuritySensitiveCallsStayOnTheFleetModel:
    def test_the_deep_agent_sanitizer_does_not_declare_a_role(self):
        """It gates sandbox network access and fails closed — never downgrade it."""
        import ast
        import pathlib

        src = pathlib.Path("my_crew/runtime_backends/deep_agent_sanitizer.py")
        tree = ast.parse(src.read_text())
        calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "complete"
        ]
        assert calls, "expected a complete() call in the sanitizer"
        for call in calls:
            assert "role" not in {k.arg for k in call.keywords}
