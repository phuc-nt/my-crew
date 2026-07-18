"""Build a Lớp B action dict for a `propose` step (v2 M3-P12 D3).

This is the ONLY place workflow proposals become action dicts. It constructs PLAIN dicts
in the EXACT shape the report writers build (so a proposed write is indistinguishable from
a report's), and imports NOTHING from `my_crew/actions/*write*` or `mcp_adapter` — the dict is
later handed to `ActionGateway.execute()` by the engine, which enqueues it as Lớp B.

`{{var}}` templates in string args are resolved from the workflow context (already-bound
read/analyze results). Templating only substitutes bound strings; a secret that slips in
still hits the gateway's Lớp A CREDENTIAL deny.
"""

from __future__ import annotations

import re
from typing import Any

_TEMPLATE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _resolve(value: Any, context: dict[str, Any]) -> Any:
    """Substitute `{{name}}` occurrences in a string from the context; pass others through."""
    if isinstance(value, str):
        return _TEMPLATE.sub(lambda m: str(context.get(m.group(1), m.group(0))), value)
    return value


def _resolved_args(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {k: _resolve(v, context) for k, v in args.items()}


def build_propose_action(target: str, args: dict[str, Any], context: dict[str, Any]) -> dict:
    """Return the action dict for a propose target. Mirrors the report writers' shapes.

    Raises if a required arg is missing (fail closed before the gateway). The returned dict
    is the gateway's input — the engine calls `gateway.execute()` on it (enqueues Lớp B).
    """
    resolved = _resolved_args(args, context)
    if target == "slack.post":
        channel = resolved.get("channel")
        text = resolved.get("text")
        if not channel or not text:
            raise ValueError("propose slack.post requires `channel` and `text`")
        # Same shape as my_crew/actions/slack_write.py deliver_report's action.
        return {
            "type": "mcp_tool",
            "server": "slack",
            "tool": "post_message",
            "args": {"channel": str(channel), "text": str(text)},
        }
    if target == "linear.comment":
        issue_id = resolved.get("issue_id") or resolved.get("issueId")
        body = resolved.get("body")
        if not issue_id or not body:
            raise ValueError("propose linear.comment requires `issue_id` and `body`")
        # Same shape as my_crew/actions/linear_write.py post_comment's action.
        return {
            "type": "mcp_tool",
            "server": "linear",
            "tool": "linear_createComment",
            "args": {"issueId": str(issue_id), "body": str(body)},
        }
    raise ValueError(f"unknown propose target {target!r}")
