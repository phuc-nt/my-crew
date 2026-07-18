"""Linear READ helpers — pull issues/projects via a config-driven Linear MCP server.

M3-P11 (C3): Linear is declared as an extra stdio MCP server in the profile
`integrations:` block (`@tacticlaunch/mcp-linear`, run as `node <dist>/index.js`).
This module resolves `config.extra_servers["linear"]` and calls the server's read
tools by their verbatim names through `mcp_adapter.call_tool` — the same READ pattern
as `jira_read`/`confluence_read` (READ does not go through the Action Gateway; only
mutations do). The gated Linear WRITE (`linear_createComment`) is added in a later slice
and is gateway-routed.

NOTE: Linear's OFFICIAL MCP is HTTP/SSE remote-only — incompatible with the agent's
stdio-spawn model — so the community stdio server is used. The dist path is
profile-configurable; nothing is hardcoded.
"""

from __future__ import annotations

import logging
from typing import Any

from my_crew.adapters.mcp_adapter import call_tool
from my_crew.config.reporting_config import McpServerSpec, ReportingConfig

logger = logging.getLogger(__name__)

# Verbatim tacticlaunch/mcp-linear read tool names (camelCase). All safe (no
# destructive substring), so they never trip the Lớp A hard-deny.
_TOOL_GET_ISSUES = "linear_getIssues"
_TOOL_SEARCH_ISSUES = "linear_searchIssues"
_TOOL_GET_PROJECTS = "linear_getProjects"


def _linear_spec(config: ReportingConfig) -> McpServerSpec:
    """Resolve the declared Linear server spec, or raise a clear setup error."""
    spec = config.extra_servers.get("linear")
    if spec is None:
        raise RuntimeError(
            "linear MCP server not declared in profile integrations: "
            "add an `integrations.linear` block (mcp_dist + required_env: [LINEAR_API_TOKEN])."
        )
    return spec


def get_issues(config: ReportingConfig, args: dict[str, Any] | None = None) -> Any:
    """List Linear issues via `linear_getIssues`. Returns the coerced tool result."""
    spec = _linear_spec(config)
    return call_tool(spec, _TOOL_GET_ISSUES, args or {})


def search_issues(config: ReportingConfig, query: str, args: dict[str, Any] | None = None) -> Any:
    """Search Linear issues via `linear_searchIssues`."""
    spec = _linear_spec(config)
    payload = {"query": query, **(args or {})}
    return call_tool(spec, _TOOL_SEARCH_ISSUES, payload)


def get_epics(config: ReportingConfig, args: dict[str, Any] | None = None) -> Any:
    """List Linear projects (epics) via `linear_getProjects`."""
    spec = _linear_spec(config)
    return call_tool(spec, _TOOL_GET_PROJECTS, args or {})
