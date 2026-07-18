"""pm-pack report-kind builders (v3 M5 S2).

The PM domain serves four report kinds. The core used to pick the builder with an
`if kind == "resource" / elif "okr" / else daily|weekly` ladder inside
`runtime/worker.py`. S2 moves that choice here: `REPORT_KINDS` maps each kind to a
builder with a *uniform* signature, so the core dispatches by lookup instead of by
hardcoded branches.

Each builder is a thin adapter over the existing `build_*_graph` in `my_crew/agent/` —
same call, same args — so pm-pack output stays byte-identical to pre-v3. The only
shape difference the adapters absorb: the daily/weekly graph takes `report_kind=`
(the kind string selects data scope + prompt framing) while okr/resource do not.
"""

from __future__ import annotations

from typing import Any

from my_crew.profile.context import ProfileContext

# Uniform builder signature every kind exposes, so the core can call any kind the
# same way: build(checkpointer, *, config, settings, context, audience, store, remember).


def _build_daily_weekly(kind: str):
    def build(
        checkpointer, *, config, settings, context: ProfileContext, audience, store, remember,
        tools=None,
    ):
        from my_crew.agent.report_graph import build_report_graph

        return build_report_graph(
            checkpointer, config=config, settings=settings, context=context,
            report_kind=kind, audience=audience, store=store, remember=remember, tools=tools,
        )

    return build


def _build_okr(
    checkpointer, *, config, settings, context: ProfileContext, audience, store, remember,
    tools=None,
):
    # OKR reads go through build_okr_rollup (okr_read), not the report ToolProvider, so
    # `tools` is accepted for the uniform builder signature but unused here in S3.
    from my_crew.agent.okr_report_graph import build_okr_graph

    return build_okr_graph(
        checkpointer, config=config, settings=settings, context=context,
        audience=audience, store=store, remember=remember,
    )


def _build_resource(
    checkpointer, *, config, settings, context: ProfileContext, audience, store, remember,
    tools=None,
):
    # Resource reads go through build_resource_rollup (jira_read), not the report
    # ToolProvider; `tools` accepted for uniformity, unused in S3.
    from my_crew.agent.resource_report_graph import build_resource_graph

    return build_resource_graph(
        checkpointer, config=config, settings=settings, context=context,
        audience=audience, store=store, remember=remember,
    )


#: kind → uniform graph builder. Consumed by the PackRegistry to populate Pack.report_kinds.
REPORT_KINDS: dict[str, Any] = {
    "daily": _build_daily_weekly("daily"),
    "weekly": _build_daily_weekly("weekly"),
    "okr": _build_okr,
    "resource": _build_resource,
}
