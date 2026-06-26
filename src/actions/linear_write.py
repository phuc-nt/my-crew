"""Linear WRITE — create a comment on a Linear issue via the Action Gateway.

M3-P11 (C3): the ONE gated Linear write this round. It MUST go through
`ActionGateway.execute`, never call the Linear MCP tool directly outside the handler.
The gateway applies the allowlist (`linear:linear_createcomment`), the Lớp A hard-deny,
the Lớp B human-approval queue (createComment is a Lớp B marker), kill-switch, dry-run,
rate-limit, idempotency, and audit. This module just supplies the handler + a wrapper.

The handler captures the server spec in the closure (NOT on the action dict) so the
token-bearing server env never enters the audit log or the persisted approval queue —
exactly the `slack_write` pattern.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from src.actions.action_gateway import ActionGateway, GatewayResult
from src.adapters.mcp_adapter import call_tool
from src.config.reporting_config import McpServerSpec, ReportingConfig

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], str]

# Verbatim tacticlaunch/mcp-linear write tool name (camelCase).
_TOOL_CREATE_COMMENT = "linear_createComment"


def make_linear_comment_handler(server: McpServerSpec) -> Handler:
    """Build a gateway handler bound to a Linear MCP server spec.

    The spec (token-bearing env) is captured in the closure rather than placed on the
    action dict, so credentials never enter the audit log or the approval store. Both the
    direct path and the approve path build a handler this way from injected config.
    """

    def _handler(action: dict[str, Any]) -> str:
        """Invoked by the gateway ONLY after all guards pass (never under dry-run)."""
        args = action.get("args", {})
        result = call_tool(server, _TOOL_CREATE_COMMENT, args)
        if isinstance(result, dict):
            comment_id = result.get("id") or (result.get("comment") or {}).get("id")
            return f"commented on {args.get('issueId')} id={comment_id}"
        return "commented"

    return _handler


def _dedup_key(issue_id: str, report_date: str) -> str:
    """Stable idempotency hint: one comment per (issue, date), not per text."""
    return f"linear-comment:{issue_id}:{report_date}"


def post_comment(
    body: str,
    *,
    gateway: ActionGateway,
    config: ReportingConfig,
    issue_id: str,
    report_date: str,
    rationale: str = "",
    approved: bool = False,
) -> GatewayResult:
    """Create a Linear comment through the gateway. Returns the gateway result.

    Lớp B: the gateway queues this for human approval (status `pending_approval`); the
    real call happens only via the approve path. `config.extra_servers["linear"]` supplies
    the server spec (injected, never a singleton). Refuses an empty body / missing issue_id
    before the gateway (mirrors `slack_write.deliver_report`). `approved=True` runs the
    already-human-approved path — skips the Lớp B enqueue; Lớp A + audit + dedup still apply.
    """
    spec = config.extra_servers.get("linear")
    if spec is None:
        raise RuntimeError(
            "linear MCP server not declared in profile integrations: cannot post a comment."
        )
    if not issue_id:
        raise ValueError("Refusing to post a Linear comment without an issue_id.")
    if not body.strip():
        raise ValueError("Refusing to post an empty Linear comment.")

    action = {
        "type": "mcp_tool",
        "server": "linear",
        "tool": _TOOL_CREATE_COMMENT,
        "args": {"issueId": issue_id, "body": body},
        "dedup_hint": _dedup_key(issue_id, report_date),
    }
    handler = make_linear_comment_handler(spec)
    if approved:
        return gateway.execute_approved(action, handler=handler, rationale=rationale)
    return gateway.execute(action, handler=handler, rationale=rationale)
