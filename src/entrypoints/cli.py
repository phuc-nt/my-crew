"""CLI entrypoint.

    uv run python -m src.entrypoints.cli "your message"   # hello-agent (Phase 0)
    uv run python -m src.entrypoints.cli report           # progress report (Phase 1)

`report` reads Jira + GitHub, detects risks, composes a report, and posts it to
Slack through the Action Gateway. Both paths need OPENROUTER_API_KEY; `report`
additionally needs the MCP server builds + tokens (see deployment-guide.md).
"""

from __future__ import annotations

import logging
import sys

from src.agent.checkpoint import get_checkpointer
from src.agent.graph import build_graph
from src.config.config_builders import (
    build_reporting_config_from_env,
    build_settings_from_env,
)


def _checkpointer(settings):
    """Open the checkpointer at the injected settings' data dir."""
    return get_checkpointer(settings.data_dir / "checkpoints.db")


def _require_key(settings) -> bool:
    if not settings.openrouter_api_key:
        print(
            "OPENROUTER_API_KEY is not set. Copy config.example.env to .env and fill it in.",
            file=sys.stderr,
        )
        return False
    return True


def _run_hello(message: str, settings) -> int:
    graph = build_graph(_checkpointer(settings), settings=settings)
    result = graph.invoke(
        {"user_input": message, "llm_response": "", "cost_usd": None},
        config={"configurable": {"thread_id": "cli"}},
    )
    print(result["llm_response"])
    cost = result.get("cost_usd")
    print(f"\n[cost: {f'${cost:.6f}' if cost is not None else 'unknown'}]", file=sys.stderr)
    return 0


def _run_report(report_kind: str, audience: str, settings, config) -> int:
    # Imported here so the hello path (and tests) don't pull in MCP/report deps.
    cp = _checkpointer(settings)
    if report_kind == "resource":
        from src.agent.resource_report_graph import build_resource_graph

        graph = build_resource_graph(cp, config=config, settings=settings, audience=audience)
    elif report_kind == "okr":
        from src.agent.okr_report_graph import build_okr_graph

        graph = build_okr_graph(cp, config=config, settings=settings, audience=audience)
    else:
        from src.agent.report_graph import build_report_graph

        graph = build_report_graph(
            cp, config=config, settings=settings, report_kind=report_kind, audience=audience
        )
    thread = f"report-{report_kind}-{audience}"
    result = graph.invoke({}, config={"configurable": {"thread_id": thread}})

    print(result.get("report_text", "(no report)"))
    cost = result.get("cost_usd")
    delivered = result.get("delivered")
    print(
        f"\n[{report_kind}/{audience} · delivered: {delivered} · "
        f"{result.get('delivery_summary', '')} · "
        f"cost: {f'${cost:.6f}' if cost is not None else 'unknown'}]",
        file=sys.stderr,
    )
    return 0


def _parse_report_kind(args: list[str]) -> str:
    """`report [--daily|--weekly|--okr|--resource]` → kind; default daily.

    Precedence when several flags are passed: resource > okr > weekly > daily.
    """
    if "--resource" in args:
        return "resource"
    if "--okr" in args:
        return "okr"
    if "--weekly" in args:
        return "weekly"
    return "daily"


def _parse_audience(args: list[str]) -> str:
    """`--audience internal|external` → audience; default internal.

    `external` composes a business-tone report and posts to the stakeholder channel
    (which routes through Lớp B human approval); anything else is internal.
    """
    return "external" if _flag_value(args, "--audience") == "external" else "internal"


def _flag_value(args: list[str], flag: str) -> str | None:
    """Return the value after `--flag` in args, or None."""
    if flag in args:
        i = args.index(flag)
        if i + 1 < len(args):
            return args[i + 1]
    return None


def _gateway(settings, config):
    """Build the Action Gateway for the management subcommands.

    Injects the per-run external-channel set so a queued external Slack post stays
    Lớp B even when re-checked here (the gateway no longer reads a config singleton).
    """
    from src.actions.action_gateway import ActionGateway

    return ActionGateway(settings, external_channels=config.slack_external_channels)


def _run_approvals(settings, config) -> int:
    """`approvals` — list Lớp B actions waiting for human approval."""
    pending = _gateway(settings, config).pending_approvals()
    if not pending:
        print("(no pending approvals)")
        return 0
    for p in pending:
        print(f"#{p.id}  {p.created_at[:19]}  {p.reason}")
        print(f"      action: {p.action}")
    return 0


def _run_approve(args: list[str], settings, config) -> int:
    """`approve <id>` / `reject <id>` — act on a queued Lớp B action."""
    if not args or not args[0].isdigit():
        print("usage: approve <id> | reject <id>", file=sys.stderr)
        return 2
    approval_id = int(args[0])
    gw = _gateway(settings, config)
    try:
        result = gw.approve(
            approval_id, handler=lambda action: _dispatch_approved_action(action, config)
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"approved #{approval_id}: {result.summary}")
    return 0


def _dispatch_approved_action(action: dict, config) -> str:
    """Live handler for an approved Lớp B action — dispatch it to its real executor.

    The queued action carries everything needed (`server`/`tool`/`args` for an MCP
    tool). Currently the only Lớp B action that enters a real flow is the external
    report's Slack post, so it routes to the Slack post handler; other server/tools
    error explicitly rather than silently no-op (so a new Lớp B flow can't be
    approved into nothing). `config` is injected so the handler stays singleton-free.
    """
    if action.get("type") == "mcp_tool" and action.get("server") == "slack":
        from src.actions.slack_write import make_slack_post_handler

        return make_slack_post_handler(config.slack_server)(action)
    label = action.get("tool") or action.get("argv") or action.get("type")
    raise RuntimeError(f"No live handler wired for approved action: {label!r}")


def _run_reject(args: list[str], settings, config) -> int:
    if not args or not args[0].isdigit():
        print("usage: reject <id>", file=sys.stderr)
        return 2
    _gateway(settings, config).reject(int(args[0]))
    print(f"rejected #{args[0]}")
    return 0


def _run_audit(args: list[str], settings) -> int:
    """`audit [--tool X] [--verdict V] [--since ISO] [--limit N]` — print audit log."""
    from src.audit.audit_log import AuditLog

    limit_raw = _flag_value(args, "--limit")
    entries = AuditLog(settings.data_dir / "audit" / "audit.jsonl").query(
        tool=_flag_value(args, "--tool"),
        verdict=_flag_value(args, "--verdict"),
        since=_flag_value(args, "--since"),
        limit=int(limit_raw) if limit_raw else 20,
    )
    if not entries:
        print("(no audit entries match)")
        return 0
    for e in entries:
        print(
            f"{e.get('timestamp', '?')[:19]}  {e.get('verdict', '?'):10}  "
            f"{e.get('tool', '?'):28}  {e.get('reason', '')[:50]}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(
            "usage: python -m src.entrypoints.cli "
            '"your message" | report [--daily|--weekly|--okr|--resource] '
            "[--audience internal|external] | audit [filters]",
            file=sys.stderr,
        )
        return 2

    # Settings is needed by every path; build it once. Reporting config is built
    # lazily (only on paths that touch Slack/Confluence) so a diagnostic command
    # like `audit` keeps working even when reporting config is misconfigured.
    settings = build_settings_from_env()

    # Commands that do NOT need an OpenRouter key (audit + approval management).
    if args[0] == "audit":
        return _run_audit(args[1:], settings)  # no reporting config needed
    if args[0] == "approvals":
        return _run_approvals(settings, build_reporting_config_from_env())
    if args[0] == "approve":
        return _run_approve(args[1:], settings, build_reporting_config_from_env())
    if args[0] == "reject":
        return _run_reject(args[1:], settings, build_reporting_config_from_env())

    if not _require_key(settings):
        return 1

    if args[0] == "report":
        return _run_report(
            _parse_report_kind(args[1:]),
            _parse_audience(args[1:]),
            settings,
            build_reporting_config_from_env(),
        )
    return _run_hello(" ".join(args), settings)  # hello: no reporting config needed


if __name__ == "__main__":
    raise SystemExit(main())
