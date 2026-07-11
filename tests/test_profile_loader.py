"""Slice 1: profile loader — default == v1 (golden), token_env, memory, env-fallback."""

from __future__ import annotations

import dataclasses as dc

import pytest

from src.config.config_builders import (
    build_reporting_config_from_env,
    build_settings_from_env,
)
from src.profile.loader import load_profile

# Env the loader + from_env read; clear all so the comparison is deterministic.
_ALL_ENV = [
    "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "OPENROUTER_REFERER", "OPENROUTER_TITLE",
    "DRY_RUN", "AGENT_WRITE_DISABLED", "MONTHLY_BUDGET_USD", "BUDGET_WARN_RATIO",
    "JIRA_PROJECT_KEY", "GITHUB_REPO", "SLACK_REPORT_CHANNEL", "SLACK_EXTERNAL_CHANNELS",
    "SLACK_STAKEHOLDER_CHANNEL", "CONFLUENCE_SPACE_KEY", "CONFLUENCE_SPACE_ID",
    "ATLASSIAN_SITE_NAME", "PR_STALE_DAYS", "BLOCKER_LABEL_SUBSTRING",
    "OKR_CONFLUENCE_PAGE_ID", "OKR_BEHIND_THRESHOLD", "RESOURCE_OVERLOAD_RATIO",
    "LABOR_COST_PER_ISSUE", "JIRA_MCP_DIST", "SLACK_MCP_DIST", "CONFLUENCE_MCP_DIST",
    "ATLASSIAN_USER_EMAIL", "ATLASSIAN_API_TOKEN", "SLACK_XOXC_TOKEN", "SLACK_XOXD_TOKEN",
    "SLACK_TEAM_DOMAIN", "TAVILY_API_KEY", "BRAVE_API_KEY",
    "FIRECRAWL_BASE_URL", "FIRECRAWL_API_KEY",
]


@pytest.fixture
def clean_env(monkeypatch):
    """Clear all builder-read env + block .env load so default == from_env is exact."""
    for k in _ALL_ENV:
        monkeypatch.delenv(k, raising=False)
    # Block .env load in all three spots that call it (loader + both env builders), so
    # the cleared process env is the only source and default == from_env is exact.
    monkeypatch.setattr("src.profile.loader.load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr("src.config.config_builders.load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr("src.config.config_builders_reporting.load_dotenv", lambda *a, **k: None)


def _write_profile(tmp_path, profile_yaml, *, soul=None, project=None, memory=None):
    """Write a tmp profiles/<id>/ dir; return (profiles_dir, profile_id)."""
    pdir = tmp_path / "profiles" / "agent"
    pdir.mkdir(parents=True)
    (pdir / "profile.yaml").write_text(profile_yaml, encoding="utf-8")
    for name, content in (("SOUL.md", soul), ("PROJECT.md", project), ("MEMORY.md", memory)):
        if content is not None:
            (pdir / name).write_text(content, encoding="utf-8")
    return tmp_path / "profiles", "agent"


# --- acceptance (a): default profile == v1 from_env, byte-for-byte ---


def test_default_profile_equals_from_env(clean_env):
    loaded = load_profile("default")
    assert dc.asdict(loaded.settings) == dc.asdict(build_settings_from_env())
    assert loaded.config == build_reporting_config_from_env()


# --- acceptance (e): token_env resolves; missing token loads, raises at spawn ---


def test_token_env_resolves_from_env(clean_env, tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_TOK", "secret-token")
    monkeypatch.setenv("ATLASSIAN_SITE_NAME", "site")
    monkeypatch.setenv("ATLASSIAN_USER_EMAIL", "me@x.com")
    pdir, pid = _write_profile(
        tmp_path,
        "bindings:\n  jira:\n    token_env: TEST_TOK\n  confluence:\n    token_env: TEST_TOK\n",
    )
    loaded = load_profile(pid, profiles_dir=pdir)
    assert loaded.config.jira_server.env["ATLASSIAN_API_TOKEN"] == "secret-token"
    assert loaded.config.confluence_server.env["CONFLUENCE_API_TOKEN"] == "secret-token"


def test_missing_token_loads_but_validate_raises(clean_env, tmp_path):
    # TEST_TOK is unset → load succeeds (lazy), validate() raises at spawn time.
    pdir, pid = _write_profile(tmp_path, "bindings:\n  jira:\n    token_env: TEST_TOK\n")
    loaded = load_profile(pid, profiles_dir=pdir)  # no raise
    with pytest.raises(RuntimeError, match="ATLASSIAN_API_TOKEN"):
        loaded.config.jira_server.validate()


# --- optional md handling + A1 memory injection (read verbatim) ---


def test_missing_optional_md_is_empty_string(clean_env, tmp_path):
    pdir, pid = _write_profile(tmp_path, "name: a\n")  # no md files
    loaded = load_profile(pid, profiles_dir=pdir)
    assert loaded.soul == "" and loaded.project == "" and loaded.memory == ""


def test_memory_md_read_verbatim(clean_env, tmp_path):
    pdir, pid = _write_profile(
        tmp_path, "name: a\n", memory="- 2026-06-20: Sprint 4 slipped due to Payment API.\n"
    )
    loaded = load_profile(pid, profiles_dir=pdir)
    assert "Sprint 4 slipped due to Payment API" in loaded.memory


# --- env-fallback rule: empty yaml scalar DEFERS to env (the load-bearing rule) ---


def test_empty_field_defers_to_env(clean_env, tmp_path, monkeypatch):
    monkeypatch.setenv("JIRA_PROJECT_KEY", "SCRUM")
    pdir, pid = _write_profile(tmp_path, 'bindings:\n  jira:\n    project_key: ""\n')
    loaded = load_profile(pid, profiles_dir=pdir)
    assert loaded.config.jira_project_key == "SCRUM"  # empty yaml did NOT clobber env


def test_yaml_value_wins_over_env(clean_env, tmp_path, monkeypatch):
    monkeypatch.setenv("JIRA_PROJECT_KEY", "SCRUM")
    pdir, pid = _write_profile(tmp_path, "bindings:\n  jira:\n    project_key: FORCED\n")
    loaded = load_profile(pid, profiles_dir=pdir)
    assert loaded.config.jira_project_key == "FORCED"  # yaml tier wins


def test_numeric_zero_threshold_survives(clean_env, tmp_path, monkeypatch):
    # 0 is a valid value (labor estimate omitted) — must NOT be treated as unset.
    monkeypatch.setenv("LABOR_COST_PER_ISSUE", "99")
    pdir, pid = _write_profile(tmp_path, "thresholds:\n  labor_cost_per_issue: 0\n")
    loaded = load_profile(pid, profiles_dir=pdir)
    assert loaded.config.labor_cost_per_issue == 0.0  # explicit 0 won, not the env 99


def test_set_but_empty_dry_run_env_coerces_to_false(clean_env, tmp_path, monkeypatch):
    # v1 parity: DRY_RUN= (set, empty) → False, NOT the default True. A set-but-empty
    # env var is passed through to _d_bool (which coerces "" → False), not omitted.
    monkeypatch.setenv("DRY_RUN", "")
    pdir, pid = _write_profile(tmp_path, "name: a\n")  # no safety section
    loaded = load_profile(pid, profiles_dir=pdir)
    assert loaded.settings.dry_run is False


def test_unset_dry_run_uses_default_true(clean_env, tmp_path):
    # Genuinely unset (not in env) ⇒ from_dict default True (clean_env deletes DRY_RUN).
    pdir, pid = _write_profile(tmp_path, "name: a\n")
    loaded = load_profile(pid, profiles_dir=pdir)
    assert loaded.settings.dry_run is True


# --- failure modes ---


def test_missing_profile_yaml_raises(clean_env, tmp_path):
    (tmp_path / "profiles").mkdir()
    with pytest.raises(FileNotFoundError, match="not found"):
        load_profile("nope", profiles_dir=tmp_path / "profiles")


def test_stakeholder_guardrail_fires_through_loader(clean_env, tmp_path):
    # stakeholder not in external set → P1 from_dict validation raises via the loader.
    yaml = (
        "bindings:\n  slack:\n    stakeholder_channel: C_EXT\n    external_channels: [C_OTHER]\n"
    )
    pdir, pid = _write_profile(tmp_path, yaml)
    with pytest.raises(RuntimeError, match="SLACK_EXTERNAL_CHANNELS"):
        load_profile(pid, profiles_dir=pdir)
