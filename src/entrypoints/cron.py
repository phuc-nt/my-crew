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
from src.config.settings import get_settings


def _report_kind(args: list[str]) -> str:
    """Cron kind from flags; same precedence as the CLI (resource>okr>weekly>daily)."""
    if "--resource" in args:
        return "resource"
    if "--okr" in args:
        return "okr"
    if "--weekly" in args:
        return "weekly"
    return "daily"


def _build_graph(report_kind: str):
    """Build the graph for a report kind (mirrors the CLI dispatch)."""
    cp = get_checkpointer()
    if report_kind == "resource":
        from src.agent.resource_report_graph import build_resource_graph

        return build_resource_graph(cp)
    if report_kind == "okr":
        from src.agent.okr_report_graph import build_okr_graph

        return build_okr_graph(cp)
    from src.agent.report_graph import build_report_graph

    return build_report_graph(cp, report_kind=report_kind)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = argv if argv is not None else sys.argv[1:]
    report_kind = _report_kind(args)

    if not get_settings().openrouter_api_key:
        print("OPENROUTER_API_KEY is not set; cannot run scheduled report.", file=sys.stderr)
        return 1

    graph = _build_graph(report_kind)
    result = graph.invoke(
        {}, config={"configurable": {"thread_id": f"cron-{report_kind}"}}
    )
    delivered = result.get("delivered", False)
    logging.getLogger(__name__).info(
        "cron %s report: delivered=%s %s",
        report_kind,
        delivered,
        result.get("delivery_summary", ""),
    )
    return 0 if delivered else 1


if __name__ == "__main__":
    raise SystemExit(main())
