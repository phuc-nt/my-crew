"""ToolCallingRuntime (v20 Phase 2) — a tool-calling loop that keeps the moat.

Class name is `ToolCallingRuntime` (NOT `CreateAgentRuntime`) to avoid colliding with the
existing `agent_create.create_agent` employee-registration function.

The safety design (red-team C1/C2/C3/H2/H4):

- **No new heavy dep (C3).** LangChain `create_agent` is not installed and churns across
  minor versions; instead this uses `langgraph.prebuilt.create_react_agent`, already in the
  dependency tree — a tool-calling loop with the same shape, no `langchain` meta-package.
- **Swaps ONLY the work loop.** It overrides `TeamTaskDeps.run_work` via
  `build_team_task_graph(work_override=...)`; perceive / self_check / rework / deliver→gateway
  stay native. So mutation-only-via-gateway holds no matter how `work` produces its text.
- **Positive read-allowlist + policy shim (C1/C2).** The loop is bound ONLY the callables from
  `build_read_toolset` — read-only, classify-shimmed, audience-aware. It can never reach a
  write/destructive tool because none is in the toolset.
- **Per-loop hard cap (H2).** A recursion/step cap bounds the loop so a runaway cannot burn the
  monthly budget; the cap is enforced in the loop config, not left to a per-tick cost check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.profile.loader import LoadedProfile

# The historical react-loop cap lives in config.py now (single source); re-exported here so
# `from tool_calling_runtime import MAX_LOOP_STEPS` still resolves (v20 back-compat).
from src.runtime_backends.config import MAX_LOOP_STEPS  # noqa: E402,F401


class ToolCallingRuntime:
    """A read-only tool-calling loop backend for team-step work."""

    def build_report(self, loaded: LoadedProfile, settings: Any, kind: str, audience: str):
        # Reports do not use a tool-calling loop in v20; the report guard in build_graph_for
        # already fails loud for non-native. Kept for Protocol shape.
        raise RuntimeError("ToolCallingRuntime chưa hỗ trợ báo cáo (report) — chỉ team-step.")

    def build_task(self, **kwargs: Any):
        from src.agent.team_task_graph import build_team_task_graph

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
        work = self._make_work_override(settings, context, config, loop_limit)
        return build_team_task_graph(work_override=work, **kwargs)

    def _make_work_override(self, settings, context, config, loop_limit):
        """Build the run_work replacement: a create_react_agent loop over the read toolset."""
        from src.runtime_backends.read_only_toolset import assert_read_only, build_read_toolset

        def _run_work(title: str, handoff: str, hook) -> tuple[str, float | None]:
            # team-step is inherently internal (no external audience). `settings` enables the
            # Firecrawl web-scrape tool when FIRECRAWL_BASE_URL is configured (v20.5).
            tools_map = build_read_toolset(config, audience="internal", settings=settings)
            assert_read_only(list(tools_map))  # defense-in-depth: prove no write tool leaked in

            from src.runtime_backends.react_loop import run_react_work

            return run_react_work(
                title=title, handoff=handoff, context=context, settings=settings,
                tools_map=tools_map, max_steps=loop_limit,
            )

        return _run_work
