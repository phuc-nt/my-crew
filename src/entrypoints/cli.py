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

from src.actions.approved_dispatch import dispatch_approved_action as _dispatch_approved_action
from src.agent.checkpoint import get_checkpointer
from src.agent.graph import build_graph
from src.profile.context import ProfileContext
from src.profile.loader import load_profile
from src.runtime.agent_paths import agent_thread_id

_DEFAULT_PROFILE = "default"


def _checkpointer(settings):
    """Open the checkpointer the injected settings select (sqlite default / postgres)."""
    return get_checkpointer(settings)


def _warn_if_migrated_to_per_agent() -> None:
    """Warn that this single-agent CLI is stale once the worker has migrated stores.

    P3's worker moves the v1 stores into `.data/agents/default/`. This CLI still reads
    the global `.data/`, so after a worker run its `audit`/`approvals` would show
    nothing — surface that instead of letting it read like data loss. (The per-agent
    view is the worker / the `mpm agent` CLI in P4.)
    """
    from src.config.settings import DATA_DIR

    if (DATA_DIR / "agents" / "default").exists() and not (DATA_DIR / "audit").exists():
        print(
            "note: stores have been migrated to .data/agents/default/ (multi-agent mode). "
            "This single-agent CLI reads the legacy .data/ and may show no audit/approvals; "
            "use the per-agent worker for the migrated data.",
            file=sys.stderr,
        )


def _parse_profile(args: list[str]) -> str:
    """`--profile <id>` → id; default `default` (the v1-equivalent agent)."""
    return _flag_value(args, "--profile") or _DEFAULT_PROFILE


def _load_or_exit(args: list[str]):
    """Load `profiles/<--profile>/`. Returns the LoadedProfile, or None on failure.

    A bad `--profile` id (FileNotFoundError) OR a config error in the profile
    (RuntimeError — e.g. the stakeholder channel not in the external set) prints a
    clear one-line error and returns None; the caller exits non-zero. Catching the
    config error here keeps diagnostic commands (`audit`) from crashing with a
    traceback when a profile is misconfigured.
    """
    try:
        return load_profile(_parse_profile(args))
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None


def _context_of(loaded) -> ProfileContext:
    """Build the prompt context (persona/project/memory) from a loaded profile."""
    return ProfileContext(persona=loaded.soul, project=loaded.project, memory=loaded.memory)


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


def _run_report(report_kind: str, audience: str, settings, config, context, profile_id: str) -> int:
    # Imported here so the hello path (and tests) don't pull in MCP/report deps.
    from src.agent.memory_node import build_remember_node
    from src.agent.store import get_store

    cp = _checkpointer(settings)
    st = get_store(settings)  # cross-thread memory Store (parity with cron/worker)
    rem = build_remember_node(profile_id, settings, audience)
    if report_kind == "resource":
        from src.agent.resource_report_graph import build_resource_graph

        graph = build_resource_graph(
            cp, config=config, settings=settings, context=context, audience=audience,
            store=st, remember=rem,
        )
    elif report_kind == "okr":
        from src.agent.okr_report_graph import build_okr_graph

        graph = build_okr_graph(
            cp, config=config, settings=settings, context=context, audience=audience,
            store=st, remember=rem,
        )
    else:
        from src.agent.report_graph import build_report_graph

        graph = build_report_graph(
            cp,
            config=config,
            settings=settings,
            context=context,
            report_kind=report_kind,
            audience=audience,
            store=st,
            remember=rem,
        )
    thread = agent_thread_id(profile_id, report_kind, audience)
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
            "usage: python -m src.entrypoints.cli [--profile <id>] "
            '"your message" | report [--daily|--weekly|--okr|--resource] '
            "[--audience internal|external] | audit [filters]\n"
            "(per-agent view: python -m src.entrypoints.mpm agent "
            "list | approvals <id> | audit <id>)",
            file=sys.stderr,
        )
        return 2

    _warn_if_migrated_to_per_agent()

    # The profile (default `default` = v1) is the single config source: it yields
    # settings + reporting config + the persona/project/memory context. A bad
    # `--profile` id prints a clear error and exits non-zero.
    loaded = _load_or_exit(args)
    if loaded is None:
        return 1
    settings, config = loaded.settings, loaded.config

    # Commands that do NOT need an OpenRouter key (audit + approval management).
    if args[0] == "audit":
        return _run_audit(args[1:], settings)
    if args[0] == "approvals":
        return _run_approvals(settings, config)
    if args[0] == "approve":
        return _run_approve(args[1:], settings, config)
    if args[0] == "reject":
        return _run_reject(args[1:], settings, config)

    if not _require_key(settings):
        return 1

    if args[0] == "report":
        return _run_report(
            _parse_report_kind(args[1:]),
            _parse_audience(args[1:]),
            settings,
            config,
            _context_of(loaded),
            loaded.profile_id,
        )
    return _run_hello(" ".join(args), settings)  # hello: no profile context


if __name__ == "__main__":
    raise SystemExit(main())
