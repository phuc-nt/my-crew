"""DeepAgentRuntime (v20 Phase 3) — isolated, optional, experimental.

⚠️ EXPERIMENTAL. `deepagents` is a Beta package that ships a "Shell access — run commands"
middleware and pulls network deps (langchain-anthropic / langsmith) that would run IN-PROCESS
with the Action Gateway and the agent's tokens (red-team C5). So this backend is deliberately
kept behind a hard boundary:

- **Lazy import.** `deepagents` is imported only inside `build_task`, never at module load —
  so a host without the optional dep imports the app fine (isolation, red-team C5).
- **Fail-loud EARLY, not per-tick.** `require_available()` lets the registry/enable path reject
  a `deep_agent` agent the moment the dep is missing, instead of every scheduled tick spawning
  a worker that exits 1 silently (red-team FM5).
- **Shell + tracing OFF; read-only toolset + policy shim.** When the dep IS present, the
  wrapper must disable the shell middleware and LangSmith tracing and bind only the Phase 2
  read-only toolset, so mutation-only-via-gateway holds even for subagents. Until that
  hardening is vendor-reviewed against a pinned `deepagents==` version, the backend refuses to
  run (raising with guidance) rather than run unsafely.

Native + ToolCallingRuntime already prove the AgentRuntime interface; this slot exists so a
`deep_agent` profile resolves to a real (if gated) backend and the isolation is testable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.profile.loader import LoadedProfile


def deepagents_available() -> bool:
    """True iff the optional `deepagents` package can be imported (no side effects)."""
    import importlib.util

    return importlib.util.find_spec("deepagents") is not None


def require_available() -> None:
    """Raise (fail-loud) if `deepagents` is not installed — call at enable/registry time.

    This surfaces the missing dep to the operator ONCE, at the moment they opt an agent into
    the deep_agent runtime, instead of a silent per-tick exit-1 loop later (red-team FM5).
    """
    if not deepagents_available():
        raise RuntimeError(
            "agent_runtime: deep_agent cần package tùy chọn 'deepagents' (chưa cài). "
            "Cài: uv sync --extra deep và bật lại — hoặc dùng agent_runtime: native/create_agent."
        )


class DeepAgentRuntime:
    """A deepagents-backed loop backend — shell runs ONLY inside a sandbox (v20.5)."""

    def build_report(self, loaded: LoadedProfile, settings: Any, kind: str, audience: str):
        raise RuntimeError("DeepAgentRuntime chưa hỗ trợ báo cáo (report) — chỉ team-step.")

    def build_task(self, **kwargs: Any):
        require_available()
        from src.agent.team_task_graph import build_team_task_graph

        settings = kwargs.get("settings")
        context = kwargs.get("context")
        kwargs.pop("reporting_config", None)  # deep agent uses its own sandbox tools, not read seam
        kwargs.pop("academic_search", None)  # read-toolset flag — the sandbox loop has no read seam
        runtime_config = kwargs.pop("runtime_config", None)
        caps = runtime_config.caps() if runtime_config is not None else None
        # Fail-closed UP-FRONT: no sandbox config / local / unknown → refuse before building the
        # graph (red-team C3 — never in-process host shell). We validate the sandbox provider here
        # (cheap, no container) so a misconfigured deep_agent fails loud immediately.
        sandbox_cfg = caps.sandbox if caps is not None else None
        loop_limit = caps.runtime_loop_limit if caps is not None else 16
        from src.runtime_backends.config import _ALLOWED_SANDBOX_PROVIDERS

        provider = (sandbox_cfg or {}).get("provider")
        if provider not in _ALLOWED_SANDBOX_PROVIDERS:
            raise RuntimeError(
                f"deep_agent cần sandbox provider hợp lệ ({sorted(_ALLOWED_SANDBOX_PROVIDERS)}); "
                f"got {provider!r} — fail-closed, không chạy shell trên host."
            )

        # Pop `telemetry` — routed into this runtime's own work loop, not the graph kwargs
        # (build_team_task_graph accepts it, but only the native deps path consumes it).
        telemetry = kwargs.pop("telemetry", None)
        work = self._make_work_override(settings, context, sandbox_cfg, loop_limit, telemetry)
        return build_team_task_graph(work_override=work, **kwargs)

    def _make_work_override(self, settings, context, sandbox_cfg, loop_limit, telemetry=None):
        """run_work replacement: a deepagents loop whose shell runs inside a token-free sandbox."""

        def _run_work(title: str, handoff: str, hook) -> tuple[str, float | None]:
            from src.runtime_backends.deep_agent_loop import run_deep_agent_work

            return run_deep_agent_work(
                title=title, handoff=handoff, context=context, settings=settings,
                sandbox_cfg=sandbox_cfg, loop_limit=loop_limit, telemetry=telemetry,
            )

        return _run_work
