"""v45 Phase 3: per-step runtime router — default create_agent, escalate on needs_shell.

Fail-closed: the light tier has no shell, so an injected needs_shell can only escalate a step to
the sandbox (safe); a needs_shell step on a sandbox-less agent fails LOUD rather than running
shell-less. A deep_agent-pinned agent's no-shell steps drop to the fast, Docker-free create_agent.
"""

from __future__ import annotations

import pytest

from my_crew.runtime_backends.config import AgentRuntimeConfig
from my_crew.runtime_backends.native_graph_runtime import NativeGraphRuntime
from my_crew.runtime_backends.protocol import (
    SandboxUnavailableForShellStep,
    resolve_step_runtime,
)


class _LP:
    def __init__(self, kind, sandbox=None):
        self.agent_runtime = AgentRuntimeConfig(kind=kind, sandbox=sandbox)
        self.profile_id = "x"


class _Step:
    def __init__(self, needs_shell=False, needs_web=True, step_type="work",
                 intervention_count=0, needs_mail=False):
        # needs_web defaults TRUE here so the tier-drop assertions below keep testing
        # on their original terms (a web-needing step); the step-type / prefetch rules
        # get their own tests at the bottom.
        self.needs_shell = needs_shell
        self.needs_web = needs_web
        self.needs_mail = needs_mail
        self.step_type = step_type
        self.intervention_count = intervention_count


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


# --- v74: tool-less steps run native one-shot -----------------------------------------


def test_a_work_step_runs_on_its_assignees_tier_even_without_web():
    """A role is (tools, permissions, model, schema): an agent the operator put on the
    tools tier is there because its steps need tools native never binds (history
    search, the read toolset). Measured live on a tools-tier fleet: the old rule sent a
    no-web work step native, no toolset was bound, and the step burned every
    intervention explaining it could not search. A native-pinned agent stays native."""
    rt = resolve_step_runtime(_LP("create_agent"), _Step(needs_web=False))
    assert _kind(rt) == "ToolCallingRuntime"
    lp = _LP("deep_agent", sandbox={"provider": "docker"})
    assert _kind(resolve_step_runtime(lp, _Step(needs_web=False))) == "ToolCallingRuntime"
    assert _kind(resolve_step_runtime(_LP("native"), _Step(needs_web=False))) == (
        "NativeGraphRuntime"
    )


def test_needs_mail_step_stays_off_the_native_tier():
    """v92: the mail tools reach a step only through the read toolset, which is wired
    for non-native tiers only. Routing a mail step native would strip the very tool it
    declared it needs — the exact dead end (`em không có quyền`) the flag exists to
    prevent. `needs_web=False` here so ONLY the mail flag can hold it off native."""
    for kind in ("create_agent", "deep_agent"):
        lp = _LP(kind, sandbox={"provider": "docker"} if kind == "deep_agent" else None)
        rt = resolve_step_runtime(lp, _Step(needs_web=False, needs_mail=True))
        assert _kind(rt) != "NativeGraphRuntime"
    # A native-pinned agent still resolves native: the flag routes the step to whatever
    # tier the agent has, it cannot conjure a tool loop the profile never configured.
    assert _kind(resolve_step_runtime(
        _LP("native"), _Step(needs_web=False, needs_mail=True))) == "NativeGraphRuntime"


def test_needs_mail_is_not_cancelled_by_prefetch():
    """`prefetched` means the launcher already fetched the step's WEB data — there is no
    prefetch seam for mail, so it must not release a mail step onto the toolless tier."""
    rt = resolve_step_runtime(
        _LP("create_agent"), _Step(needs_web=False, needs_mail=True), prefetched=True,
    )
    assert _kind(rt) != "NativeGraphRuntime"


def test_review_row_is_always_native():
    rt = resolve_step_runtime(
        _LP("deep_agent", sandbox={"provider": "docker"}),
        _Step(needs_web=True, step_type="review"),
    )
    assert _kind(rt) == "NativeGraphRuntime"


def test_a_prefetched_work_step_runs_native_until_a_ruling_re_arms_the_tier():
    """`prefetched` means the launcher already put the step's web data in the prompt —
    the web capability the tier held over native is spent, so the fast one-shot tier
    runs. After a coordinator ruling (intervention_count >= 1) the agent's own tier is
    back, so a wrong hint costs one attempt, not the step."""
    lp = _LP("create_agent")
    assert _kind(resolve_step_runtime(lp, _Step(), prefetched=True)) == "NativeGraphRuntime"
    rt = resolve_step_runtime(lp, _Step(intervention_count=1), prefetched=True)
    assert _kind(rt) == "ToolCallingRuntime"


def test_rework_row_keeps_the_agent_tier():
    """Fixing a DATA defect may need the tools the original work had (round-7 lesson:
    a toolless fixer degrades honestly but uselessly)."""
    rt = resolve_step_runtime(_LP("create_agent"), _Step(needs_web=False, step_type="rework"))
    assert _kind(rt) == "ToolCallingRuntime"


def test_a_sprint_step_is_always_native_even_when_it_needs_web():
    """v77: the sprint pipeline rides `work_override`, a seam only the native runtime
    honors. Routing it to a tool-calling tier would discard the whole code-paced
    pipeline and hand the model back the react loop sprint mode exists to avoid."""
    rt = resolve_step_runtime(
        _LP("create_agent"), _Step(needs_web=True, step_type="sprint"),
    )
    assert _kind(rt) == "NativeGraphRuntime"


def test_a_sprint_step_stays_native_after_a_coordinator_ruling():
    """Self-heal re-arms the agent tier for a mis-hinted WORK step; a sprint step has
    no react loop to fall back to, so the pin must survive an intervention."""
    rt = resolve_step_runtime(
        _LP("deep_agent", sandbox={"provider": "docker"}),
        _Step(needs_web=True, step_type="sprint", intervention_count=1),
    )
    assert _kind(rt) == "NativeGraphRuntime"
