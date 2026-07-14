"""AgentRuntime Protocol + resolver (v20 Phase 1).

Two methods, not one union — the report builder (`build_graph_for(loaded, settings, kind,
audience)`) and the team-step builder (`build_team_task_graph(**kwargs)` with task_id /
data_dir / step context, no audience) have incompatible shapes; forcing them into one
`build(spec)` breeds dead params. So the Protocol exposes `build_report` and `build_task`.

`resolve_runtime(loaded)` picks the backend from `loaded.agent_runtime.kind`:
  - "native"       → NativeGraphRuntime (the existing graphs, byte-identical)
  - "create_agent" → RuntimeError (Phase 2)
  - "deep_agent"   → RuntimeError (Phase 3)
  - anything else  → RuntimeError (fail-loud)

`loaded=None` (a team-step whose profile could not load — a live, supported degrade path)
resolves to native. `RUNTIME_FORCE_NATIVE=1` (env) forces native fleet-wide regardless of
profile — the kill-switch for reverting the whole fleet while investigating a runtime.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.profile.loader import LoadedProfile


@runtime_checkable
class AgentRuntime(Protocol):
    """One employee's loop backend. Produces a compiled graph the orchestrator runs.

    Invariant across ALL implementations (THE INVARIANT): the runtime never writes
    external directly — its only external-write path is the graph's `deliver` node routing
    through the Action Gateway. A tool-calling runtime must additionally confine its toolset
    to read-only + internal-artifact and route every in-loop tool through hard_block.classify
    (Phase 2).
    """

    def build_report(self, loaded: LoadedProfile, settings: Any, kind: str, audience: str):
        """Build the compiled graph for a report kind (daily/weekly/okr/resource)."""
        ...

    def build_task(self, **kwargs: Any):
        """Build the compiled graph for one team-task step (kwargs mirror build_team_task_graph)."""
        ...


def _forced_native() -> bool:
    """The RUNTIME_FORCE_NATIVE kill-switch: any truthy env value forces native."""
    return os.environ.get("RUNTIME_FORCE_NATIVE", "").strip().lower() in {"1", "true", "yes", "on"}


def runtime_kind_for(loaded: LoadedProfile | None) -> str:
    """The effective runtime kind for a profile, honoring None-degrade + the kill-switch.

    Kept separate from `resolve_runtime` so the report-build guard (`build_graph_for`) can
    ask "is this agent native?" cheaply without constructing a runtime object.
    """
    if loaded is None or _forced_native():
        return "native"
    cfg = getattr(loaded, "agent_runtime", None)
    return getattr(cfg, "kind", "native") if cfg is not None else "native"


def resolve_runtime(loaded: LoadedProfile | None) -> AgentRuntime:
    """Resolve the AgentRuntime for a profile (None → native; kill-switch → native)."""
    return _runtime_for_kind(runtime_kind_for(loaded))


def _runtime_for_kind(kind: str) -> AgentRuntime:
    from src.runtime_backends.native_graph_runtime import NativeGraphRuntime

    if kind == "native":
        return NativeGraphRuntime()
    if kind == "create_agent":
        from src.runtime_backends.tool_calling_runtime import ToolCallingRuntime

        return ToolCallingRuntime()
    if kind == "deep_agent":
        from src.runtime_backends.deep_agent_runtime import DeepAgentRuntime

        return DeepAgentRuntime()
    raise RuntimeError(
        f"agent_runtime {kind!r} không hợp lệ (known: native, create_agent, deep_agent)."
    )


class SandboxUnavailableForShellStep(RuntimeError):
    """A step declared needs_shell but its assignee has no sandbox to run shell safely.

    Fail-closed: rather than silently drop a shell step to a shell-less tier (which would run
    the step but never actually run the shell it needs → silent underdelivery), the step fails
    loudly so the operator sees the mis-assignment. Real shell only ever runs in the sandbox.
    """


def resolve_step_runtime(loaded: LoadedProfile | None, step: Any) -> AgentRuntime:
    """v45 per-step routing: pick the runtime for ONE step by its `needs_shell` flag + the
    assignee profile's configured kind.

    Rules (fail-closed by construction — the light tier has NO shell):
      - `needs_shell=True`  → deep_agent (Docker sandbox). The profile MUST carry a sandbox config;
        if not, raise `SandboxUnavailableForShellStep` (never run shell-less silently).
      - `needs_shell=False` on a **deep_agent-pinned** agent → DROP to create_agent (the speed
        win: a no-shell step should not pay for a Docker container). deep_agent's only distinct
        capability is shell, which this step declared it doesn't need.
      - otherwise → the profile's own kind, UNCHANGED (native stays native, create_agent stays
        create_agent) — backward compatible, no behavior change for existing non-deep_agent agents.

    Injection safety: an injected `needs_shell` can only ESCALATE a step to the sandbox (safe) or,
    if flipped False, drop it to the shell-less tier where a genuinely-shell task simply fails —
    it can never grant host/shell access a step wasn't already routed to.
    """
    from src.runtime_backends.native_graph_runtime import NativeGraphRuntime

    if loaded is None or _forced_native():
        return NativeGraphRuntime()

    profile_kind = runtime_kind_for(loaded)
    needs_shell = bool(getattr(step, "needs_shell", False))

    if needs_shell:
        cfg = getattr(loaded, "agent_runtime", None)
        caps = cfg.caps() if cfg is not None and hasattr(cfg, "caps") else None
        sandbox = getattr(caps, "sandbox", None) if caps is not None else None
        if not sandbox:
            raise SandboxUnavailableForShellStep(
                f"step cần shell (needs_shell) nhưng agent "
                f"{getattr(loaded, 'profile_id', '?')!r} không có cấu hình sandbox — fail-closed, "
                "không chạy shell trên host. Giao bước này cho một agent deep_agent có sandbox."
            )
        return _runtime_for_kind("deep_agent")

    # no-shell: a deep_agent-pinned agent drops to the fast, Docker-free create_agent tier.
    if profile_kind == "deep_agent":
        return _runtime_for_kind("create_agent")
    return _runtime_for_kind(profile_kind)
