"""Provider registry config: validation rules and the profile.yaml→Settings path.

`providers` is the one config block that sits next to secrets, so its rules are
load-bearing in two directions:

- A malformed or missing entry must raise at load, not at the first LLM call hours
  later — by then the only symptom is a confusing upstream 404 from an endpoint the
  operator did not know was being used.
- Only environment variable NAMES may land in yaml. A pasted key would be committed
  the moment someone shares a company.yaml, so the shape check rejects it outright
  rather than trusting the author to notice.
"""

from __future__ import annotations

import pytest

from my_crew.config.config_builders import build_settings_from_dict
from my_crew.profile.loader import load_profile

_SPEC = {"base_url": "https://api.vendor.test/v1", "api_key_env": "VENDOR_KEY"}


def _write_profile(tmp_path, body: str):
    d = tmp_path / "tester"
    d.mkdir(parents=True, exist_ok=True)
    (d / "profile.yaml").write_text(body, encoding="utf-8")
    return load_profile("tester", profiles_dir=tmp_path).settings


class TestProvidersValidation:
    def test_absent_means_no_registry_and_pre_v91_behavior(self):
        assert build_settings_from_dict({}).providers == ()

    def test_a_yaml_mapping_becomes_name_url_env_triples(self):
        s = build_settings_from_dict({"providers": {"vendor": _SPEC}})
        assert s.providers == (("vendor", "https://api.vendor.test/v1", "VENDOR_KEY"),)

    def test_the_env_string_form_parses_the_same_registry(self):
        """A fleet that configures everything through .env needs a flat form, the same
        way `role_models` accepts "role=model,..."."""
        s = build_settings_from_dict(
            {"providers": "vendor=https://api.vendor.test/v1|VENDOR_KEY,b=https://b.test/v1|B_KEY"}
        )
        assert s.providers == (
            ("vendor", "https://api.vendor.test/v1", "VENDOR_KEY"),
            ("b", "https://b.test/v1", "B_KEY"),
        )

    def test_openrouter_cannot_be_redefined(self):
        """It is the implicit provider of every bare `org/model` entry — pointing it
        elsewhere would silently redirect the entire fleet, not just one chain."""
        with pytest.raises(ValueError, match="reserved"):
            build_settings_from_dict({"providers": {"openrouter": _SPEC}})

    @pytest.mark.parametrize("name", ["Vendor", "ven dor", "ven:dor", "ven/dor"])
    def test_a_name_that_cannot_be_a_prefix_is_rejected(self, name):
        with pytest.raises(ValueError, match="lowercase letters"):
            build_settings_from_dict({"providers": {name: _SPEC}})

    def test_a_base_url_without_a_scheme_is_rejected(self):
        with pytest.raises(ValueError, match="http"):
            build_settings_from_dict(
                {"providers": {"v": {"base_url": "api.v.test/v1", "api_key_env": "V_KEY"}}}
            )

    def test_an_api_key_env_holding_a_key_instead_of_a_name_is_rejected(self):
        """The one mistake that leaks a secret into a committed file."""
        with pytest.raises(ValueError, match="never the key value"):
            build_settings_from_dict(
                {"providers": {"v": {"base_url": "https://api.v.test/v1",
                                     "api_key_env": "sk-live-abc123"}}}
            )

    def test_a_missing_api_key_env_is_rejected_rather_than_defaulted(self):
        with pytest.raises(ValueError, match="api_key_env"):
            build_settings_from_dict(
                {"providers": {"v": {"base_url": "https://api.v.test/v1"}}}
            )

    def test_a_non_mapping_spec_is_rejected(self):
        with pytest.raises(ValueError, match="must be a mapping"):
            build_settings_from_dict({"providers": {"v": "https://api.v.test/v1"}})

    def test_a_malformed_env_string_entry_names_the_expected_shape(self):
        with pytest.raises(ValueError, match=r"name=base_url\|API_KEY_ENV"):
            build_settings_from_dict({"providers": "vendor=https://api.v.test/v1"})


class TestProvidersFromProfileYaml:
    def test_a_yaml_registry_reaches_settings_and_resolves(self, tmp_path):
        s = _write_profile(
            tmp_path,
            "name: Tester\n"
            "providers:\n"
            "  vendor:\n"
            "    base_url: https://api.vendor.test/v1\n"
            "    api_key_env: VENDOR_KEY\n",
        )
        assert s.provider_for("vendor") == ("https://api.vendor.test/v1", "VENDOR_KEY")

    def test_a_profile_registry_beats_the_env_string(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_CREW_PROVIDERS", "vendor=https://wrong.test/v1|WRONG_KEY")
        s = _write_profile(
            tmp_path,
            "name: Tester\n"
            "providers:\n"
            "  vendor:\n"
            "    base_url: https://api.vendor.test/v1\n"
            "    api_key_env: VENDOR_KEY\n",
        )
        assert s.provider_for("vendor") == ("https://api.vendor.test/v1", "VENDOR_KEY")

    def test_the_env_registry_is_used_only_when_the_profile_is_silent(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("MY_CREW_PROVIDERS", "vendor=https://api.vendor.test/v1|VENDOR_KEY")
        s = _write_profile(tmp_path, "name: Tester\n")
        assert s.provider_for("vendor") == ("https://api.vendor.test/v1", "VENDOR_KEY")

    def test_a_profile_with_no_providers_key_declares_nothing(self, tmp_path):
        assert _write_profile(tmp_path, "name: Tester\n").providers == ()

    def test_a_role_model_may_point_at_a_registry_provider(self, tmp_path):
        """The composition Phase 1+3+4 exist for: the advisor runs on a different
        vendor entirely, and still degrades UP to the fleet model when it fails."""
        s = _write_profile(
            tmp_path,
            "name: Tester\n"
            "model: org/fleet\n"
            "role_models:\n"
            "  advisor: vendor::sharp-model\n"
            "providers:\n"
            "  vendor:\n"
            "    base_url: https://api.vendor.test/v1\n"
            "    api_key_env: VENDOR_KEY\n",
        )
        assert s.model_for_role("advisor") == ("vendor::sharp-model", "org/fleet")
