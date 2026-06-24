"""Cron entrypoint — run a scheduled report (daily, weekly, okr, or resource).

Invoked by launchd (see deploy/launchd/) or any scheduler:

    python -m src.entrypoints.cron --daily
    python -m src.entrypoints.cron --weekly
    python -m src.entrypoints.cron --resource

Delegates to the same report flow as the CLI. Exit non-zero on failure so the
scheduler can surface it. Honors DRY_RUN / AGENT_WRITE_DISABLED like every run.
"""

from __future__ import annotations

import logging
import sys

from src.agent.checkpoint import get_checkpointer
from src.profile.context import ProfileContext
from src.profile.loader import load_profile
from src.runtime.agent_paths import agent_thread_id


def _profile_id(args: list[str]) -> str:
    """`--profile <id>` → id; default `default` (the v1-equivalent agent)."""
    if "--profile" in args:
        i = args.index("--profile")
        if i + 1 < len(args):
            return args[i + 1]
    return "default"


def _report_kind(args: list[str]) -> str:
    """Cron kind from flags; same precedence as the CLI (resource>okr>weekly>daily)."""
    if "--resource" in args:
        return "resource"
    if "--okr" in args:
        return "okr"
    if "--weekly" in args:
        return "weekly"
    return "daily"


def _audience(args: list[str]) -> str:
    """`--audience external` → external; default internal (same as the CLI)."""
    if "--audience" in args:
        i = args.index("--audience")
        if i + 1 < len(args) and args[i + 1] == "external":
            return "external"
    return "internal"


def _build_graph(report_kind: str, audience: str, settings, config, context):
    """Build the graph for a report kind (mirrors the CLI dispatch)."""
    cp = get_checkpointer(settings.data_dir / "checkpoints.db")
    if report_kind == "resource":
        from src.agent.resource_report_graph import build_resource_graph

        return build_resource_graph(
            cp, config=config, settings=settings, context=context, audience=audience
        )
    if report_kind == "okr":
        from src.agent.okr_report_graph import build_okr_graph

        return build_okr_graph(
            cp, config=config, settings=settings, context=context, audience=audience
        )
    from src.agent.report_graph import build_report_graph

    return build_report_graph(
        cp,
        config=config,
        settings=settings,
        context=context,
        report_kind=report_kind,
        audience=audience,
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = argv if argv is not None else sys.argv[1:]
    report_kind = _report_kind(args)
    audience = _audience(args)

    try:
        loaded = load_profile(_profile_id(args))
    except (FileNotFoundError, RuntimeError) as exc:
        # Bad --profile id OR a config error in the profile → clean exit, no traceback.
        print(f"error: {exc}", file=sys.stderr)
        return 1
    settings, config = loaded.settings, loaded.config
    context = ProfileContext(
        persona=loaded.soul, project=loaded.project, memory=loaded.memory
    )

    if not settings.openrouter_api_key:
        print("OPENROUTER_API_KEY is not set; cannot run scheduled report.", file=sys.stderr)
        return 1

    # An external cron → Lớp B → pending_approval → delivered=True (queued is success),
    # but NOT posted until a human approves: the correct guardrail for stakeholder updates.
    graph = _build_graph(report_kind, audience, settings, config, context)
    thread_id = agent_thread_id(loaded.profile_id, report_kind, audience)
    result = graph.invoke({}, config={"configurable": {"thread_id": thread_id}})
    delivered = result.get("delivered", False)
    logging.getLogger(__name__).info(
        "cron %s/%s report: delivered=%s %s",
        report_kind,
        audience,
        delivered,
        result.get("delivery_summary", ""),
    )
    return 0 if delivered else 1


if __name__ == "__main__":
    raise SystemExit(main())
