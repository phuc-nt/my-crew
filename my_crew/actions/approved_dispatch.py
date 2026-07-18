"""Live dispatch for an approved Lớp B action (v2 M2-P7, extracted shared).

When a human approves a queued Lớp B action, the gateway runs it through this handler.
The queued action carries everything needed (`server`/`tool`/`args` for an MCP tool).
Currently the only Lớp B action that enters a real flow is the external report's Slack
post, so it routes to the Slack post handler; any other server/tool errors explicitly
rather than silently no-op (so a new Lớp B flow can't be approved into nothing).

Extracted here because cli.py, mpm_manage_cmds.py AND the M2-P7 web approve route all
need the SAME handler — previously duplicated in the two entrypoints. The
`make_slack_post_handler` import stays LAZY inside the function so the existing test
monkeypatch target (`my_crew.actions.slack_write.make_slack_post_handler`) still works.
`config` is injected so the handler stays singleton-free.
"""

from __future__ import annotations

from collections.abc import Callable

#: Native types whose handler needs the AGENT's identity (a closure over its profile id).
#: `dispatch_approved_action` alone cannot run them — see `make_agent_bound_dispatch`.
_AGENT_BOUND_TYPES = frozenset({"schedule_update", "team_task_create", "team_task_move"})


def make_agent_bound_dispatch(profile_id: str, config) -> Callable[[dict], str]:
    """Dispatch for call sites that HOLD the agent's identity (web approve, mpm, chat).

    v31 P2: native action types like `schedule_update` are self-only BY ARCHITECTURE —
    the target agent is a closure over `profile_id` taken from the call site's `loaded`
    profile, NEVER read from the action dict (nothing to forge). Everything else falls
    through to the shared `dispatch_approved_action` unchanged.
    """

    def _handler(action: dict) -> str:
        atype = str(action.get("type"))
        if atype == "schedule_update":
            from my_crew.actions.schedule_write import make_schedule_update_handler

            return make_schedule_update_handler(profile_id)(action)
        if atype in ("team_task_create", "team_task_move"):
            from my_crew.actions.team_task_write import make_team_task_handler

            return make_team_task_handler(profile_id)(action)
        return dispatch_approved_action(action, config)

    return _handler


def dispatch_approved_action(action: dict, config) -> str:
    """Dispatch an approved Lớp B action to its real executor; return the summary."""
    if action.get("type") == "mcp_tool" and action.get("server") == "slack":
        from my_crew.actions.slack_write import make_slack_post_handler

        return make_slack_post_handler(config.slack_server)(action)
    # M3-P11 (C3): an approved Linear comment routes to the Linear write handler. The
    # server spec comes from the injected config (token-bearing env stays in the closure,
    # never on the persisted action). Lazy import keeps the monkeypatch target stable.
    # v5 M12: an approved Jira write (chat-command createIssue/addComment) routes to
    # the Jira MCP server from the injected config — same closure posture as Slack.
    if action.get("type") == "mcp_tool" and action.get("server") == "jira":
        from my_crew.actions.jira_write import make_jira_tool_handler

        return make_jira_tool_handler(config.jira_server)(action)
    if action.get("type") == "mcp_tool" and action.get("server") == "linear":
        from my_crew.actions.linear_write import make_linear_comment_handler

        spec = (config.extra_servers or {}).get("linear")
        if spec is None:
            raise RuntimeError("linear MCP server not declared; cannot dispatch approved comment.")
        return make_linear_comment_handler(spec)(action)
    # v31 P4: an approved gws Sheets/Docs write spawns the gws CLI. No agent identity
    # needed (the CLI's own OAuth is the credential), so it lives in the SHARED dispatch
    # — every approve path (web/mpm/chat AND legacy cli) can run it.
    if action.get("type") == "gws_write":
        from my_crew.actions.gws_write import make_gws_handler

        return make_gws_handler()(action)
    # M3-P11 (D2): an approved outbound email routes to the SMTP handler. The SMTP config
    # (and the env-resolved password) stay in the handler closure, never on the action.
    if action.get("type") == "email_send":
        from my_crew.actions.email_write import make_email_handler

        smtp = getattr(config, "smtp", None)
        if smtp is None:
            raise RuntimeError("smtp not configured; cannot dispatch approved email.")
        return make_email_handler(smtp)(action)
    if str(action.get("type")) in _AGENT_BOUND_TYPES:
        # The legacy CLI approve path has no loaded profile, so it cannot build the
        # identity closure. Explicit, named refusal — never a silent no-op.
        raise RuntimeError(
            f"action type {action.get('type')!r} needs an agent-bound handler — approve "
            "it from the dashboard, `mpm agent approve`, or chat (legacy CLI approve "
            "does not support this type)."
        )
    label = action.get("tool") or action.get("argv") or action.get("type")
    raise RuntimeError(f"No live handler wired for approved action: {label!r}")
