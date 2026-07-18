"""Jira write handler — execute an APPROVED Jira MCP action (v5 M12).

Jira writes were allowlisted (createIssue/addComment) since v1 but nothing ever
dispatched them — reports only read Jira. Chat-commands make them real: an approved
`{server: "jira", tool, args}` action routes here. Same shape as the Slack/Linear
handlers: the token-bearing server spec stays in the closure (injected from config at
dispatch time), never on the persisted action. This module is only ever invoked by
`approve()` — after Lớp A + allowlist + a HUMAN said yes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from my_crew.adapters.mcp_adapter import call_tool
from my_crew.config.reporting_config import McpServerSpec

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], str]


def make_jira_tool_handler(server: McpServerSpec) -> Handler:
    """Build a gateway handler bound to the Jira MCP server spec."""

    def _handler(action: dict[str, Any]) -> str:
        tool = str(action.get("tool") or "")
        result = call_tool(server, tool, action.get("args", {}))
        if isinstance(result, dict):
            key = result.get("key") or (result.get("issue") or {}).get("key")
            if key:
                return f"jira {tool}: {key}"
        return f"jira {tool}: done"

    return _handler
