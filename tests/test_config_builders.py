"""Slice A: config builders — from_dict pure + validated, from_env byte-identical."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config.config_builders import (
    build_reporting_config_from_dict,
    build_reporting_config_from_env,
    build_settings_from_dict,
    build_settings_from_env,
)
from src.config.settings import DATA_DIR, DEFAULT_MODEL

# Env vars the builders read (clear all so defaults apply deterministically).
_SETTINGS_ENV = [
    "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "OPENROUTER_REFERER", "OPENROUTER_TITLE",
    "DRY_RUN", "AGENT_WRITE_DISABLED", "MONTHLY_BUDGET_USD", "BUDGET_WARN_RATIO",
]
_REPORTING_ENV = [
    "JIRA_PROJECT_KEY", "GITHUB_REPO", "SLACK_REPORT_CHANNEL", "SLACK_EXTERNAL_CHANNELS",
    "SLACK_STAKEHOLDER_CHANNEL", "CONFLUENCE_SPACE_KEY", "CONFLUENCE_SPACE_ID",
    "ATLASSIAN_SITE_NAME", "PR_STALE_DAYS", "BLOCKER_LABEL_SUBSTRING",
    "OKR_CONFLUENCE_PAGE_ID", "OKR_BEHIND_THRESHOLD", "RESOURCE_OVERLOAD_RATIO",
    "LABOR_COST_PER_ISSUE", "JIRA_MCP_DIST", "SLACK_MCP_DIST", "CONFLUENCE_MCP_DIST",
    "ATLASSIAN_USER_EMAIL", "ATLASSIAN_API_TOKEN", "SLACK_XOXC_TOKEN", "SLACK_XOXD_TOKEN",
    "SLACK_TEAM_DOMAIN",
]


@pytest.fixture
def clean_env(monkeypatch):
    for k in _SETTINGS_ENV + _REPORTING_ENV:
        monkeypatch.delenv(k, raising=False)
    # Block the .env file load so from_env sees only the (cleared) process env.
    # (settings builders + reporting builders each import load_dotenv in their own module.)
    monkeypatch.setattr("src.config.config_builders.load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr("src.config.config_builders_reporting.load_dotenv", lambda *a, **k: None)


# --- from_dict: defaults (pure, all-optional keys) ---


def test_settings_from_dict_defaults():
    s = build_settings_from_dict({})
    assert s.openrouter_api_key is None
    assert s.openrouter_model == DEFAULT_MODEL
    assert s.dry_run is True and s.write_disabled is False
    assert s.monthly_budget_usd == 50.0 and s.budget_warn_ratio == 0.8
    assert s.data_dir == DATA_DIR


def test_reporting_from_dict_defaults():
    c = build_reporting_config_from_dict({})
    assert c.jira_project_key is None and c.github_repo is None
    assert c.slack_external_channels == frozenset()
    assert c.pr_stale_days == 7 and c.blocker_label_substring == "block"
    assert c.okr_behind_threshold == 0.5 and c.resource_overload_ratio == 1.5
    assert c.labor_cost_per_issue == 0.0
    assert c.jira_server.name == "jira" and c.slack_server.name == "slack"


# --- from_dict: coercion (str OR typed both work — profile vs caller) ---


def test_settings_from_dict_coercion():
    assert build_settings_from_dict({"dry_run": "false"}).dry_run is False
    assert build_settings_from_dict({"dry_run": False}).dry_run is False
    assert build_settings_from_dict({"dry_run": "yes"}).dry_run is True
    assert build_settings_from_dict({"monthly_budget_usd": "12.5"}).monthly_budget_usd == 12.5
    assert build_settings_from_dict({"monthly_budget_usd": 12.5}).monthly_budget_usd == 12.5


def test_reporting_from_dict_coercion():
    assert build_reporting_config_from_dict({"pr_stale_days": "3"}).pr_stale_days == 3
    assert build_reporting_config_from_dict({"pr_stale_days": 3}).pr_stale_days == 3
    # external channels: comma-string OR iterable
    by_str = build_reporting_config_from_dict({"slack_external_channels": "#a, #b"})
    by_list = build_reporting_config_from_dict({"slack_external_channels": ["#a", "#b"]})
    assert by_str.slack_external_channels == frozenset({"#a", "#b"})
    assert by_list.slack_external_channels == frozenset({"#a", "#b"})


def test_settings_from_dict_data_dir_override():
    s = build_settings_from_dict({"data_dir": "/tmp/agent-x"})
    assert s.data_dir == Path("/tmp/agent-x")  # the P3 per-agent isolation hook


def test_reporting_from_dict_mcp_dist_override():
    c = build_reporting_config_from_dict({"jira_mcp_dist": "/custom/jira/dist.js"})
    assert c.jira_server.dist_path == Path("/custom/jira/dist.js")


def test_reporting_from_dict_tokens_land_in_server_env():
    c = build_reporting_config_from_dict(
        {"atlassian_api_token": "ATX", "atlassian_user_email": "e@x", "atlassian_site_name": "s"}
    )
    assert c.jira_server.env["ATLASSIAN_API_TOKEN"] == "ATX"
    assert c.confluence_server.env["CONFLUENCE_API_TOKEN"] == "ATX"  # reuses Atlassian cred


# --- validation lives in from_dict (both paths enforce it) ---


def test_stakeholder_not_in_external_raises_on_dict_path():
    with pytest.raises(RuntimeError, match="SLACK_EXTERNAL_CHANNELS"):
        build_reporting_config_from_dict(
            {"slack_stakeholder_channel": "#exec", "slack_external_channels": ""}
        )


def test_stakeholder_in_external_ok():
    c = build_reporting_config_from_dict(
        {"slack_stakeholder_channel": "#exec", "slack_external_channels": "#exec"}
    )
    assert c.slack_stakeholder_channel == "#exec"


def test_stakeholder_validation_via_env_path(clean_env, monkeypatch):
    monkeypatch.setenv("SLACK_STAKEHOLDER_CHANNEL", "#exec")
    monkeypatch.setenv("SLACK_EXTERNAL_CHANNELS", "")  # not in set
    with pytest.raises(RuntimeError, match="SLACK_EXTERNAL_CHANNELS"):
        build_reporting_config_from_env()


# --- from_env byte-identical to v1 defaults (golden) ---


def test_settings_from_env_golden_defaults(clean_env):
    s = build_settings_from_env()
    assert s == build_settings_from_dict({"data_dir": DATA_DIR})  # env-empty == dict defaults


def test_reporting_from_env_golden_defaults(clean_env):
    c = build_reporting_config_from_env()
    expected = build_reporting_config_from_dict({})
    # Compare every scalar field (server specs compared by name + dist default).
    assert c.jira_project_key == expected.jira_project_key
    assert c.slack_external_channels == expected.slack_external_channels
    assert c.pr_stale_days == expected.pr_stale_days
    assert c.okr_behind_threshold == expected.okr_behind_threshold
    assert c.jira_server.dist_path == expected.jira_server.dist_path


def test_settings_from_env_reads_values(clean_env, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("MONTHLY_BUDGET_USD", "25")
    s = build_settings_from_env()
    assert s.openrouter_api_key == "sk-test"
    assert s.dry_run is False and s.monthly_budget_usd == 25.0
