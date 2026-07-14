"""v45 Phase 3: per-step runtime router — default create_agent, escalate on needs_shell.

Fail-closed: the light tier has no shell, so an injected needs_shell can only escalate a step to
the sandbox (safe); a needs_shell step on a sandbox-less agent fails LOUD rather than running
shell-less. A deep_agent-pinned agent's no-shell steps drop to the fast, Docker-free create_agent.
"""

from __future__ import annotations

import pytest

from src.runtime_backends.config import AgentRuntimeConfig
from src.runtime_backends.native_graph_runtime import NativeGraphRuntime
from src.runtime_backends.protocol import (
    SandboxUnavailableForShellStep,
    resolve_step_runtime,
)


class _LP:
    def __init__(self, kind, sandbox=None):
        self.agent_runtime = AgentRuntimeConfig(kind=kind, sandbox=sandbox)
        self.profile_id = "x"


class _Step:
    def __init__(self, needs_shell=False):
        self.needs_shell = needs_shell


def _kind(rt) -> str:
    return type(rt).__name__


def test_none_profile_is_native():
    assert isinstance(resolve_step_runtime(None, _Step()), NativeGraphRuntime)


def test_no_shell_deep_agent_drops_to_create_agent():
    """The speed win: a no-shell step on a deep_agent agent runs on the Docker-free tier."""
    rt = resolve_step_runtime(_LP("deep_agent", sandbox={"provider": "docker"}), _Step(False))
    assert _kind(rt) == "ToolCallingRuntime"  # create_agent, no Docker


def test_needs_shell_escalates_to_deep_agent():
    rt = resolve_step_runtime(_LP("deep_agent", sandbox={"provider": "docker"}), _Step(True))
    assert _kind(rt) == "DeepAgentRuntime"


def test_needs_shell_without_sandbox_fails_closed():
    """A needs_shell step on a sandbox-less agent must FAIL LOUD, not run shell-less."""
    with pytest.raises(SandboxUnavailableForShellStep):
        resolve_step_runtime(_LP("create_agent", sandbox=None), _Step(True))
    # even a create_agent agent (no sandbox) cannot serve a shell step
    with pytest.raises(SandboxUnavailableForShellStep):
        resolve_step_runtime(_LP("native", sandbox=None), _Step(True))


def test_create_agent_profile_unchanged_for_no_shell():
    assert _kind(resolve_step_runtime(_LP("create_agent"), _Step(False))) == "ToolCallingRuntime"


def test_native_profile_unchanged_for_no_shell():
    """Backward compat: a native agent's no-shell step stays native (no tool-loop regression)."""
    assert isinstance(resolve_step_runtime(_LP("native"), _Step(False)), NativeGraphRuntime)


def test_injection_flip_cannot_grant_shell_below_declaration():
    """A no-shell step routed to create_agent has NO shell tier — flipping needs_shell False can
    only remove shell, never grant it. (needs_shell True is the ONLY path to a sandbox.)"""
    # no-shell → create_agent (ToolCalling), which has no execute/shell tool at all
    rt = resolve_step_runtime(_LP("deep_agent", sandbox={"provider": "docker"}), _Step(False))
    assert _kind(rt) == "ToolCallingRuntime"  # shell-less by construction


def test_force_native_killswitch(monkeypatch):
    monkeypatch.setenv("RUNTIME_FORCE_NATIVE", "1")
    # even a needs_shell step goes native under the fleet kill-switch (no runtime escalation)
    rt = resolve_step_runtime(_LP("deep_agent", sandbox={"provider": "docker"}), _Step(True))
    assert isinstance(rt, NativeGraphRuntime)
