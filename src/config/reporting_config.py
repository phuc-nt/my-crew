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

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

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


@lru_cache(maxsize=1)
def get_reporting_config() -> ReportingConfig:
    """Load .env once and return cached reporting config.

    DEPRECATED (v2 M1-P1): thin wrapper over `build_reporting_config_from_env()`
    while the config singletons are being phased out. The env→config logic + the
    stakeholder-channel validation now live in `config_builders.from_dict`. Removed
    entirely in M1-P1 Slice D; callers should receive `ReportingConfig` injected.
    """
    from src.config.config_builders import build_reporting_config_from_env

    return build_reporting_config_from_env()
