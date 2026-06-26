"""Live dispatch for an approved Lớp B action (v2 M2-P7, extracted shared).

When a human approves a queued Lớp B action, the gateway runs it through this handler.
The queued action carries everything needed (`server`/`tool`/`args` for an MCP tool).
Currently the only Lớp B action that enters a real flow is the external report's Slack
post, so it routes to the Slack post handler; any other server/tool errors explicitly
rather than silently no-op (so a new Lớp B flow can't be approved into nothing).

Extracted here because cli.py, mpm_manage_cmds.py AND the M2-P7 web approve route all
need the SAME handler — previously duplicated in the two entrypoints. The
`make_slack_post_handler` import stays LAZY inside the function so the existing test
monkeypatch target (`src.actions.slack_write.make_slack_post_handler`) still works.
`config` is injected so the handler stays singleton-free.
"""

from __future__ import annotations


def dispatch_approved_action(action: dict, config) -> str:
    """Dispatch an approved Lớp B action to its real executor; return the summary."""
    if action.get("type") == "mcp_tool" and action.get("server") == "slack":
        from src.actions.slack_write import make_slack_post_handler

        return make_slack_post_handler(config.slack_server)(action)
    # M3-P11 (C3): an approved Linear comment routes to the Linear write handler. The
    # server spec comes from the injected config (token-bearing env stays in the closure,
    # never on the persisted action). Lazy import keeps the monkeypatch target stable.
    if action.get("type") == "mcp_tool" and action.get("server") == "linear":
        from src.actions.linear_write import make_linear_comment_handler

        spec = (config.extra_servers or {}).get("linear")
        if spec is None:
            raise RuntimeError("linear MCP server not declared; cannot dispatch approved comment.")
        return make_linear_comment_handler(spec)(action)
    label = action.get("tool") or action.get("argv") or action.get("type")
    raise RuntimeError(f"No live handler wired for approved action: {label!r}")
