"""v3 M5 S1: pack scaffolding + `domain` field.

Covers the seam introduced before any code moves onto packs:
- `domain:` parses from profile.yaml; absent/blank ⇒ "pm" (backward-compat).
- `PackRegistry.load` returns an (empty) Pack for a known domain, raises on unknown.
- A scaffold Pack is inert: every contribution collection is empty.
"""

from __future__ import annotations

import pytest

from src.packs import DEFAULT_DOMAIN, Pack, PackRegistry, ToolProvider
from src.profile.loader import load_profile


def _write_profile(tmp_path, profile_yaml):
    pdir = tmp_path / "profiles" / "agent"
    pdir.mkdir(parents=True)
    (pdir / "profile.yaml").write_text(profile_yaml, encoding="utf-8")
    return tmp_path / "profiles", "agent"


@pytest.fixture
def no_dotenv(monkeypatch):
    """Block .env load so domain parsing is the only variable under test."""
    monkeypatch.setattr("src.profile.loader.load_dotenv", lambda *a, **k: None)


# --- domain field on the profile loader ---


def test_absent_domain_defaults_to_pm(no_dotenv, tmp_path):
    pdir, pid = _write_profile(tmp_path, "name: a\n")  # no domain: declared
    loaded = load_profile(pid, profiles_dir=pdir)
    assert loaded.domain == "pm"


def test_blank_domain_defaults_to_pm(no_dotenv, tmp_path):
    pdir, pid = _write_profile(tmp_path, 'name: a\ndomain: ""\n')
    loaded = load_profile(pid, profiles_dir=pdir)
    assert loaded.domain == "pm"


def test_explicit_domain_is_parsed(no_dotenv, tmp_path):
    pdir, pid = _write_profile(tmp_path, "name: a\ndomain: hr\n")
    loaded = load_profile(pid, profiles_dir=pdir)
    assert loaded.domain == "hr"


def test_domain_is_stripped(no_dotenv, tmp_path):
    pdir, pid = _write_profile(tmp_path, "name: a\ndomain: '  pm  '\n")
    loaded = load_profile(pid, profiles_dir=pdir)
    assert loaded.domain == "pm"


# --- PackRegistry resolution ---


def test_registry_loads_known_domain():
    pack = PackRegistry().load("pm")
    assert isinstance(pack, Pack)
    assert pack.domain == "pm"


def test_registry_none_resolves_to_default():
    assert PackRegistry().load(None).domain == DEFAULT_DOMAIN


def test_registry_blank_resolves_to_default():
    assert PackRegistry().load("   ").domain == DEFAULT_DOMAIN


def test_registry_unknown_domain_raises():
    # A domain with no domain-packs/<x>-pack/ folder fails loudly (default-DENY holds).
    with pytest.raises(ValueError, match="Unknown domain 'nope'"):
        PackRegistry().load("nope")


def test_registry_discovers_pm_from_filesystem():
    # Discovery is filesystem-based (M6): pm is found via its pack folder, not a hardcode.
    from src.packs.registry import discover_domains

    assert "pm" in discover_domains()


def test_pack_loads_as_importable_package():
    # A pack is registered as an importable package (domain_pack_<domain>) so its own
    # modules can import siblings — needed by self-contained packs (HR), harmless to PM.
    import sys

    from src.packs.registry import _load_pack_module, _pack_package_name

    _load_pack_module("pm", "graphs")
    assert _pack_package_name("pm") in sys.modules  # package registered
    assert f"{_pack_package_name('pm')}.graphs" in sys.modules  # submodule loaded


def test_all_report_kinds_is_union_across_packs():
    # Kind validation (CLI/API) uses this union so a pack's kind is valid without a core
    # edit. It must contain every PM kind plus any other installed pack's kinds.
    from src.packs.registry import all_report_kinds

    kinds = all_report_kinds()
    assert {"daily", "weekly", "okr", "resource"} <= kinds  # PM kinds always present


# --- S2: pm-pack registers its report kinds, other seams still empty ---


def test_pm_pack_registers_all_four_report_kinds():
    pack = PackRegistry().load("pm")
    assert set(pack.report_kinds) == {"daily", "weekly", "okr", "resource"}
    assert all(callable(b) for b in pack.report_kinds.values())


def test_pm_pack_contributes_allowlist_matching_core_default():
    # S4: the pack supplies the MCP allowlist (server→tools), and PM's must equal the
    # core default so behavior is byte-identical. Normalized to lowercased frozensets.
    from src.actions.hard_block import _DEFAULT_MCP_ALLOWLIST, _normalize_allowlist

    pack = PackRegistry().load("pm")
    assert _normalize_allowlist(pack.allowlist) == _DEFAULT_MCP_ALLOWLIST


def test_pm_pack_bundles_prompts_and_skills_after_s5():
    # S5: PM system-prompt strings + skill .md files are now pack assets.
    pack = PackRegistry().load("pm")
    assert "report-system" in pack.prompts
    assert "report-detail-system" in pack.prompts
    assert pack.prompts["report-system"].startswith("Bạn là một PM/SM")
    assert set(pack.skills) == {
        "estimate-effort", "fetch-jira-epics", "flag-risk",
        "parse-github-labels", "prioritize-blockers",
    }


def test_daily_and_weekly_use_distinct_builders():
    # The two share an underlying graph but bind a different report_kind, so the
    # registry must map them to different closures (not the same object).
    pack = PackRegistry().load("pm")
    assert pack.report_kinds["daily"] is not pack.report_kinds["weekly"]


def test_tool_provider_is_runtime_checkable():
    # A bare object is not a ToolProvider; one with read() is. Confirms the Protocol
    # contract the PM provider (S3) and HR provider (M6) implement.
    class _Reader:
        def read(self, kind, config, settings):
            return None

    assert isinstance(_Reader(), ToolProvider)
    assert not isinstance(object(), ToolProvider)
