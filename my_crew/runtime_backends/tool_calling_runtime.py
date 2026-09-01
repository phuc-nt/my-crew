"""ToolCallingRuntime (v20 Phase 2) — a tool-calling loop that keeps the moat.

Class name is `ToolCallingRuntime` (NOT `CreateAgentRuntime`) to avoid colliding with the
existing `agent_create.create_agent` employee-registration function.

The safety design:

- **Community-standard loop.** The work loop is `langchain.agents.create_agent` (langchain 1.x),
  run in `react_loop.run_react_work`. langsmith tracing is forced off per-invoke there.
- **Swaps ONLY the work loop.** It overrides `TeamTaskDeps.run_work` via
  `build_team_task_graph(work_override=...)`; perceive / self_check / rework / deliver→gateway
  stay native. So mutation-only-via-gateway holds no matter how `work` produces its text.
- **Positive read-allowlist + policy shim.** The loop is bound ONLY the callables from
  `build_read_toolset` — read-only, classify-shimmed, audience-aware. It can never reach a
  write/destructive tool because none is in the toolset.
- **Per-loop hard cap.** A recursion/step cap bounds the loop so a runaway cannot burn the
  monthly budget; the cap is enforced in the loop config, not left to a per-tick cost check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from my_crew.profile.loader import LoadedProfile

# The historical react-loop cap lives in config.py now (single source); re-exported here so
# `from tool_calling_runtime import MAX_LOOP_STEPS` still resolves (v20 back-compat).
from my_crew.runtime_backends.config import MAX_LOOP_STEPS  # noqa: E402,F401


class ToolCallingRuntime:
    """A read-only tool-calling loop backend for team-step work."""

    def build_report(self, loaded: LoadedProfile, settings: Any, kind: str, audience: str):
        # Reports do not use a tool-calling loop in v20; the report guard in build_graph_for
        # already fails loud for non-native. Kept for Protocol shape.
        raise RuntimeError("ToolCallingRuntime chưa hỗ trợ báo cáo (report) — chỉ team-step.")

    def build_task(self, **kwargs: Any):
        from my_crew.agent.team_task_graph import build_team_task_graph

        settings = kwargs.get("settings")
        context = kwargs.get("context")
        config = kwargs.pop("reporting_config", None)  # optional, threaded by the runner
        # v20.5: per-runtime loop cap from the agent's AgentRuntimeConfig; falls back to the
        # create_agent default (MAX_LOOP_STEPS) when the runner did not thread a config.
        runtime_config = kwargs.pop("runtime_config", None)
        loop_limit = (
            runtime_config.caps().runtime_loop_limit
            if runtime_config is not None else MAX_LOOP_STEPS
        )
        # The step's own spend ceiling, threaded down the same path as the round cap. None
        # (every tier's default, and the case where the runner threaded no config) leaves
        # the loop bounded only by rounds — the pre-existing behaviour.
        cost_cap_usd = (
            runtime_config.caps().cost_cap_usd if runtime_config is not None else None
        )
        # v86: which work-loop engine runs the tools tier — `thin` (self-owned flat loop,
        # default) or `langchain` (create_agent react loop, kept selectable for A/B).
        loop_engine = (
            runtime_config.loop_engine if runtime_config is not None else "thin"
        )
        # Pop `telemetry` here — build_team_task_graph accepts the param but only its native
        # deps use it; this runtime routes telemetry into its own work loop instead, so it must
        # NOT also ride **kwargs into the graph (double-wire).
        telemetry = kwargs.pop("telemetry", None)
        # Retired academic-search opt-in: still popped so a profile that predates the
        # removal loads instead of raising when the stale key rides **kwargs into the graph.
        kwargs.pop("academic_search", None)
        # v39 #1: the agent's Google-Workspace-read opt-in (threaded from the loaded profile).
        gws_context = bool(kwargs.pop("gws_context", False))
        # v73: the agent's web-search opt-in — the SAME profile flag that arms the native
        # pre-work hook, threaded so the loop tier can search too (not just scrape).
        web_search = bool(kwargs.pop("web_search", False))
        # v43/v44: deep_team + its cap override are deep_agent-only opt-ins; the tools tier has no
        # sandbox/subagents, so pop-and-ignore (else they'd ride **kwargs into the graph and raise).
        kwargs.pop("deep_team", None)
        kwargs.pop("deep_team_max_calls", None)
        work = self._make_work_override(settings, context, config, loop_limit, telemetry,
                                        gws_context, web_search, loop_engine,
                                        cost_cap_usd)
        return build_team_task_graph(work_override=work, **kwargs)

    def _make_work_override(self, settings, context, config, loop_limit, telemetry=None,
                            gws_context=False, web_search=False,
                            loop_engine="thin", cost_cap_usd=None):
        """Build the run_work replacement: a tool loop over the read toolset."""
        from my_crew.runtime_backends.read_only_toolset import assert_read_only, build_read_toolset

        def _run_work(title: str, handoff: str, hook) -> tuple[str, float | None]:
            # team-step is inherently internal (no external audience). `settings` enables the
            # Firecrawl web-scrape tool when FIRECRAWL_BASE_URL is configured (v20.5).
            tools_map = build_read_toolset(config, audience="internal", settings=settings,
                                           gws_context=gws_context, web_search=web_search)
            assert_read_only(list(tools_map))  # defense-in-depth: prove no write tool leaked in

            if loop_engine == "langchain":
                from my_crew.runtime_backends.react_loop import run_react_work

                return run_react_work(
                    title=title, handoff=handoff, context=context, settings=settings,
                    tools_map=tools_map, max_steps=loop_limit, telemetry=telemetry,
                )

            from my_crew.runtime_backends.thin_tool_loop import run_thin_loop

            return run_thin_loop(
                title=title, handoff=handoff, context=context, settings=settings,
                tools_map=tools_map, max_steps=loop_limit, telemetry=telemetry,
                cost_cap_usd=cost_cap_usd,
            )

        return _run_work
