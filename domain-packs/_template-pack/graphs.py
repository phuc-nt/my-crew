"""_template-pack graphs (v20 authoring skeleton).

`REPORT_KINDS` maps each report kind to a uniform builder the core dispatches. This template
reuses the core `build_report_graph` for its one `example` kind so the skeleton runs out of the
box; a real pack replaces the builder body with its own perceive→analyze→compose→deliver graph
(see hr-pack/graphs.py for a domain that supplies a NEW analyzer + ToolProvider).

The builder signature is fixed — the core calls every kind the same way:
    build(checkpointer, *, config, settings, context, audience, store, remember, tools=None)
"""

from __future__ import annotations

from typing import Any


def _build_example(
    checkpointer, *, config, settings, context, audience, store, remember, tools=None,
):
    # Skeleton: reuse the core daily/weekly report graph. Swap this for your domain's graph.
    from my_crew.agent.report_graph import build_report_graph

    return build_report_graph(
        checkpointer, config=config, settings=settings, context=context,
        report_kind="daily", audience=audience, store=store, remember=remember, tools=tools,
    )


#: kind → uniform builder. Consumed by PackRegistry to populate Pack.report_kinds.
REPORT_KINDS: dict[str, Any] = {
    "example": _build_example,
}
