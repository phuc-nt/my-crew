"""Phase 1 reporting + MCP/CLI integration config (env-loaded).

Kept separate from `settings.py` (LLM + guardrail config) so each concern stays
small. Holds: which Jira project / GitHub repo / Slack channel to report on, the
risk thresholds, and how to launch each stdio MCP server (dist path + the env
vars that server reads). Tokens are passed down to the spawned server's env;
the agent does not use them directly.

Validation is lazy: a missing server token raises only when that server is
actually spawned, so unit tests and unrelated flows run without credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from src.config.settings import REPO_ROOT

# Default dist paths for the local MCP server repos (overridable via env).
_DEFAULT_JIRA_DIST = Path.home() / "workspace" / "jira-cloud-mcp-server" / "dist" / "index.js"
_DEFAULT_SLACK_DIST = Path.home() / "workspace" / "slack-browser-mcp-server" / "dist" / "index.js"
_DEFAULT_CONFLUENCE_DIST = (
    Path.home() / "workspace" / "confluence-cloud-mcp-server" / "dist" / "index.js"
)


@dataclass(frozen=True)
class McpServerSpec:
    """How to spawn one stdio MCP server: node entry + the env it reads."""

    name: str
    dist_path: Path
    env: dict[str, str]
    required_env_keys: tuple[str, ...]

    def validate(self) -> None:
        """Raise a clear error if the dist build or required env is missing.

        Called right before spawning the server, not at import.
        """
        if not self.dist_path.exists():
            raise FileNotFoundError(
                f"MCP server {self.name!r} dist not found at {self.dist_path}. "
                f"Build it: cd <repo> && npm install && npm run build."
            )
        missing = [k for k in self.required_env_keys if not self.env.get(k)]
        if missing:
            raise RuntimeError(
                f"MCP server {self.name!r} missing required env: {', '.join(missing)}. "
                f"Set them in .env (see config.example.env)."
            )


@dataclass(frozen=True)
class ReportingConfig:
    """Target project/repo/channel + risk thresholds for the report flow."""

    jira_project_key: str | None
    github_repo: str | None  # "owner/repo"
    slack_report_channel: str | None
    # Channels treated as external/stakeholder → posting needs human approval (Lớp B).
    slack_external_channels: frozenset[str]
    # Phase 5: the single channel external/stakeholder reports post to. MUST be in
    # slack_external_channels (validated at load) so it routes through Lớp B approval.
    slack_stakeholder_channel: str | None

    # Confluence target for the detail report (Slice 2).
    confluence_space_key: str | None
    confluence_space_id: str | None
    atlassian_site_name: str | None  # used to build a page URL fallback

    # Risk thresholds (defaults; tune later via env).
    pr_stale_days: int
    blocker_label_substring: str  # an issue label containing this => blocker

    # Phase 3: OKR tracking. The OKR table lives on this Confluence page; an
    # Objective rolling up below `okr_behind_threshold` (fraction 0..1) is flagged
    # "at risk". Both optional — OKR features no-op cleanly when the page is unset.
    okr_confluence_page_id: str | None
    okr_behind_threshold: float

    # Phase 4: resource + cost. Overload = open-count above team_mean × ratio.
    # labor_cost_per_issue == 0 ⇒ labor estimate omitted from the report.
    resource_overload_ratio: float
    labor_cost_per_issue: float

    jira_server: McpServerSpec
    slack_server: McpServerSpec
    confluence_server: McpServerSpec


def _server_dist(env_key: str, default: Path) -> Path:
    raw = os.getenv(env_key)
    return Path(raw) if raw else default


@lru_cache(maxsize=1)
def get_reporting_config() -> ReportingConfig:
    """Load .env once and return cached reporting config."""
    load_dotenv(REPO_ROOT / ".env")

    jira_server = McpServerSpec(
        name="jira",
        dist_path=_server_dist("JIRA_MCP_DIST", _DEFAULT_JIRA_DIST),
        env={
            "ATLASSIAN_SITE_NAME": os.getenv("ATLASSIAN_SITE_NAME", ""),
            "ATLASSIAN_USER_EMAIL": os.getenv("ATLASSIAN_USER_EMAIL", ""),
            "ATLASSIAN_API_TOKEN": os.getenv("ATLASSIAN_API_TOKEN", ""),
        },
        required_env_keys=("ATLASSIAN_SITE_NAME", "ATLASSIAN_USER_EMAIL", "ATLASSIAN_API_TOKEN"),
    )
    slack_server = McpServerSpec(
        name="slack",
        dist_path=_server_dist("SLACK_MCP_DIST", _DEFAULT_SLACK_DIST),
        env={
            "SLACK_XOXC_TOKEN": os.getenv("SLACK_XOXC_TOKEN", ""),
            "SLACK_XOXD_TOKEN": os.getenv("SLACK_XOXD_TOKEN", ""),
            "SLACK_TEAM_DOMAIN": os.getenv("SLACK_TEAM_DOMAIN", ""),
        },
        required_env_keys=("SLACK_XOXC_TOKEN", "SLACK_XOXD_TOKEN", "SLACK_TEAM_DOMAIN"),
    )
    # Confluence reuses the same Atlassian credential as Jira (same Cloud site).
    confluence_server = McpServerSpec(
        name="confluence",
        dist_path=_server_dist("CONFLUENCE_MCP_DIST", _DEFAULT_CONFLUENCE_DIST),
        env={
            "CONFLUENCE_SITE_NAME": os.getenv("ATLASSIAN_SITE_NAME", ""),
            "CONFLUENCE_EMAIL": os.getenv("ATLASSIAN_USER_EMAIL", ""),
            "CONFLUENCE_API_TOKEN": os.getenv("ATLASSIAN_API_TOKEN", ""),
        },
        required_env_keys=("CONFLUENCE_SITE_NAME", "CONFLUENCE_EMAIL", "CONFLUENCE_API_TOKEN"),
    )

    external_channels = frozenset(
        c.strip() for c in os.getenv("SLACK_EXTERNAL_CHANNELS", "").split(",") if c.strip()
    )
    stakeholder_channel = os.getenv("SLACK_STAKEHOLDER_CHANNEL") or None
    # Guardrail: the stakeholder channel MUST be in the external set, else an external
    # report would auto-post to stakeholders without Lớp B approval.
    if stakeholder_channel and stakeholder_channel not in external_channels:
        raise RuntimeError(
            f"SLACK_STAKEHOLDER_CHANNEL ({stakeholder_channel!r}) must also be listed in "
            "SLACK_EXTERNAL_CHANNELS so external reports route through Lớp B approval. "
            "Add it to SLACK_EXTERNAL_CHANNELS in .env."
        )

    return ReportingConfig(
        jira_project_key=os.getenv("JIRA_PROJECT_KEY") or None,
        github_repo=os.getenv("GITHUB_REPO") or None,
        slack_report_channel=os.getenv("SLACK_REPORT_CHANNEL") or None,
        slack_external_channels=external_channels,
        slack_stakeholder_channel=stakeholder_channel,
        confluence_space_key=os.getenv("CONFLUENCE_SPACE_KEY") or None,
        confluence_space_id=os.getenv("CONFLUENCE_SPACE_ID") or None,
        atlassian_site_name=os.getenv("ATLASSIAN_SITE_NAME") or None,
        pr_stale_days=int(os.getenv("PR_STALE_DAYS", "7")),
        blocker_label_substring=os.getenv("BLOCKER_LABEL_SUBSTRING", "block"),
        okr_confluence_page_id=os.getenv("OKR_CONFLUENCE_PAGE_ID") or None,
        okr_behind_threshold=float(os.getenv("OKR_BEHIND_THRESHOLD", "0.5")),
        resource_overload_ratio=float(os.getenv("RESOURCE_OVERLOAD_RATIO", "1.5")),
        labor_cost_per_issue=float(os.getenv("LABOR_COST_PER_ISSUE", "0")),
        jira_server=jira_server,
        slack_server=slack_server,
        confluence_server=confluence_server,
    )
