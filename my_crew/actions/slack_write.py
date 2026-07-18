"""Slack write — post a report message via the Action Gateway.

The only mutation in Slice 1. It must go through `ActionGateway.execute`, never
call the Slack MCP tool directly outside the handler. The gateway applies the
allowlist (`slack:post_message`), Lớp A hard-deny, kill-switch, dry-run,
rate-limit, idempotency, and audit — this module just supplies the handler and a
convenience wrapper.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from my_crew.actions.action_gateway import ActionGateway, GatewayResult
from my_crew.adapters.mcp_adapter import call_tool
from my_crew.config.reporting_config import McpServerSpec, ReportingConfig

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], str]


def make_slack_post_handler(server: McpServerSpec) -> Handler:
    """Build a gateway handler bound to a Slack MCP server spec.

    The spec is captured in the closure rather than placed on the action dict, so
    the token-bearing server env never enters the audit log or the persisted
    approval queue. Both the direct path (`deliver_report`) and the approve path
    (CLI `_dispatch_approved_action`) build a handler this way from injected config.
    """

    def _handler(action: dict[str, Any]) -> str:
        """Invoked by the gateway ONLY after all guards pass (never under dry-run)."""
        args = action.get("args", {})
        result = call_tool(server, "post_message", args)
        if isinstance(result, dict):
            ts = result.get("ts") or (result.get("message") or {}).get("ts")
            channel = result.get("channel") or args.get("channel")
            return f"posted to {channel} ts={ts}"
        return "posted"

    return _handler


def _dedup_key(channel: str, report_date: str) -> str:
    """Stable idempotency hint: one report per (channel, date), not per text.

    Report text varies each LLM run, so deduping on text would never catch a
    re-run. Keying on channel+date prevents double-posting the same day's report.
    """
    return f"slack-report:{channel}:{report_date}"


def deliver_report(
    text: str,
    *,
    gateway: ActionGateway,
    config: ReportingConfig,
    channel: str | None = None,
    report_date: str,
    rationale: str = "",
    approved: bool = False,
) -> GatewayResult:
    """Post a report to Slack through the gateway. Returns the gateway result.

    `report_date` (YYYY-MM-DD) makes the action idempotent per day+channel.
    `config` supplies the Slack server spec and default channel; it is injected
    so this writer never reads a config singleton. `approved=True` (M2-P5 graph
    interrupt resume) runs the already-human-approved path — skips the Lớp B
    enqueue, Lớp A + audit + dedup still apply.
    """
    target = channel or config.slack_report_channel
    if not target:
        raise RuntimeError("SLACK_REPORT_CHANNEL is not set (in .env or passed explicitly).")
    if not text.strip():
        raise ValueError("Refusing to post an empty report.")

    action = {
        "type": "mcp_tool",
        "server": "slack",
        "tool": "post_message",
        "args": {"channel": target, "text": text},
        # Idempotency marker consumed by the gateway's dedup (stable per day).
        "dedup_hint": _dedup_key(target, report_date),
    }
    handler = make_slack_post_handler(config.slack_server)
    if approved:
        return gateway.execute_approved(action, handler=handler, rationale=rationale)
    return gateway.execute(action, handler=handler, rationale=rationale)
