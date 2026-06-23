"""ReportingConfig builders — from_dict core + from_env wrapper (v2 M1-P1).

Split out of `config_builders.py` to keep each file under the 200-LOC gate. Shares
the dict-coercion helpers with the settings builders. `config_builders` re-exports
these so the public import path is `from src.config.config_builders import ...`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.config.config_builders_helpers import _d_float, _d_int, _d_str_or_none
from src.config.reporting_config import (
    _DEFAULT_CONFLUENCE_DIST,
    _DEFAULT_JIRA_DIST,
    _DEFAULT_SLACK_DIST,
    McpServerSpec,
    ReportingConfig,
)


def _build_servers(d: dict[str, Any]) -> tuple[McpServerSpec, McpServerSpec, McpServerSpec]:
    """Assemble the 3 stdio MCP server specs from the dict (dist + token env)."""
    site = str(d.get("atlassian_site_name") or "")
    email = str(d.get("atlassian_user_email") or "")
    token = str(d.get("atlassian_api_token") or "")

    jira = McpServerSpec(
        name="jira",
        dist_path=Path(d.get("jira_mcp_dist") or _DEFAULT_JIRA_DIST),
        env={
            "ATLASSIAN_SITE_NAME": site,
            "ATLASSIAN_USER_EMAIL": email,
            "ATLASSIAN_API_TOKEN": token,
        },
        required_env_keys=("ATLASSIAN_SITE_NAME", "ATLASSIAN_USER_EMAIL", "ATLASSIAN_API_TOKEN"),
    )
    slack = McpServerSpec(
        name="slack",
        dist_path=Path(d.get("slack_mcp_dist") or _DEFAULT_SLACK_DIST),
        env={
            "SLACK_XOXC_TOKEN": str(d.get("slack_xoxc_token") or ""),
            "SLACK_XOXD_TOKEN": str(d.get("slack_xoxd_token") or ""),
            "SLACK_TEAM_DOMAIN": str(d.get("slack_team_domain") or ""),
        },
        required_env_keys=("SLACK_XOXC_TOKEN", "SLACK_XOXD_TOKEN", "SLACK_TEAM_DOMAIN"),
    )
    # Confluence reuses the same Atlassian credential as Jira (same Cloud site).
    confluence = McpServerSpec(
        name="confluence",
        dist_path=Path(d.get("confluence_mcp_dist") or _DEFAULT_CONFLUENCE_DIST),
        env={
            "CONFLUENCE_SITE_NAME": site,
            "CONFLUENCE_EMAIL": email,
            "CONFLUENCE_API_TOKEN": token,
        },
        required_env_keys=("CONFLUENCE_SITE_NAME", "CONFLUENCE_EMAIL", "CONFLUENCE_API_TOKEN"),
    )
    return jira, slack, confluence


def _coerce_external_channels(val: Any) -> frozenset[str]:
    """A comma-string or an iterable of channel names → a clean frozenset."""
    if not val:
        return frozenset()
    if isinstance(val, str):
        return frozenset(c.strip() for c in val.split(",") if c.strip())
    return frozenset(str(c).strip() for c in val if str(c).strip())


def build_reporting_config_from_dict(d: dict[str, Any]) -> ReportingConfig:
    """Build ReportingConfig from a plain dict. Pure; holds the only validation."""
    external_channels = _coerce_external_channels(d.get("slack_external_channels"))
    stakeholder_channel = _d_str_or_none(d, "slack_stakeholder_channel")
    # Guardrail (Phase 5): the stakeholder channel MUST be in the external set, else an
    # external report would auto-post to stakeholders without Lớp B approval.
    if stakeholder_channel and stakeholder_channel not in external_channels:
        raise RuntimeError(
            f"SLACK_STAKEHOLDER_CHANNEL ({stakeholder_channel!r}) must also be listed in "
            "SLACK_EXTERNAL_CHANNELS so external reports route through Lớp B approval. "
            "Add it to SLACK_EXTERNAL_CHANNELS in .env."
        )

    jira_server, slack_server, confluence_server = _build_servers(d)
    return ReportingConfig(
        jira_project_key=_d_str_or_none(d, "jira_project_key"),
        github_repo=_d_str_or_none(d, "github_repo"),
        slack_report_channel=_d_str_or_none(d, "slack_report_channel"),
        slack_external_channels=external_channels,
        slack_stakeholder_channel=stakeholder_channel,
        confluence_space_key=_d_str_or_none(d, "confluence_space_key"),
        confluence_space_id=_d_str_or_none(d, "confluence_space_id"),
        atlassian_site_name=_d_str_or_none(d, "atlassian_site_name"),
        pr_stale_days=_d_int(d, "pr_stale_days", 7),
        blocker_label_substring=d.get("blocker_label_substring") or "block",
        okr_confluence_page_id=_d_str_or_none(d, "okr_confluence_page_id"),
        okr_behind_threshold=_d_float(d, "okr_behind_threshold", 0.5),
        resource_overload_ratio=_d_float(d, "resource_overload_ratio", 1.5),
        labor_cost_per_issue=_d_float(d, "labor_cost_per_issue", 0.0),
        jira_server=jira_server,
        slack_server=slack_server,
        confluence_server=confluence_server,
    )


def build_reporting_config_from_env() -> ReportingConfig:
    """Load .env + read os.environ into a dict, then delegate to from_dict.

    Reproduces the v1 env-loaded reporting config exactly (same keys, same coercion).
    """
    from src.config.settings import REPO_ROOT

    load_dotenv(REPO_ROOT / ".env")
    return build_reporting_config_from_dict(
        {
            "jira_project_key": os.getenv("JIRA_PROJECT_KEY"),
            "github_repo": os.getenv("GITHUB_REPO"),
            "slack_report_channel": os.getenv("SLACK_REPORT_CHANNEL"),
            "slack_external_channels": os.getenv("SLACK_EXTERNAL_CHANNELS", ""),
            "slack_stakeholder_channel": os.getenv("SLACK_STAKEHOLDER_CHANNEL"),
            "confluence_space_key": os.getenv("CONFLUENCE_SPACE_KEY"),
            "confluence_space_id": os.getenv("CONFLUENCE_SPACE_ID"),
            "atlassian_site_name": os.getenv("ATLASSIAN_SITE_NAME"),
            "pr_stale_days": os.getenv("PR_STALE_DAYS"),
            "blocker_label_substring": os.getenv("BLOCKER_LABEL_SUBSTRING"),
            "okr_confluence_page_id": os.getenv("OKR_CONFLUENCE_PAGE_ID"),
            "okr_behind_threshold": os.getenv("OKR_BEHIND_THRESHOLD"),
            "resource_overload_ratio": os.getenv("RESOURCE_OVERLOAD_RATIO"),
            "labor_cost_per_issue": os.getenv("LABOR_COST_PER_ISSUE"),
            # server dist overrides + token env (read directly from env in P1, as v1):
            "jira_mcp_dist": os.getenv("JIRA_MCP_DIST"),
            "slack_mcp_dist": os.getenv("SLACK_MCP_DIST"),
            "confluence_mcp_dist": os.getenv("CONFLUENCE_MCP_DIST"),
            "atlassian_user_email": os.getenv("ATLASSIAN_USER_EMAIL"),
            "atlassian_api_token": os.getenv("ATLASSIAN_API_TOKEN"),
            "slack_xoxc_token": os.getenv("SLACK_XOXC_TOKEN"),
            "slack_xoxd_token": os.getenv("SLACK_XOXD_TOKEN"),
            "slack_team_domain": os.getenv("SLACK_TEAM_DOMAIN"),
        }
    )
