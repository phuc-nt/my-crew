"""v20.5 Phase 1: per-runtime caps — runtime_loop_limit + sandbox validation + config→runtime."""

from __future__ import annotations

import pytest

from src.runtime_backends.config import (
    MAX_LOOP_STEPS,
    AgentRuntimeConfig,
    parse_agent_runtime_config,
)


def test_default_loop_limit_per_kind():
    assert parse_agent_runtime_config("native").caps().runtime_loop_limit == 0
    assert parse_agent_runtime_config("create_agent").caps().runtime_loop_limit == MAX_LOOP_STEPS
    assert parse_agent_runtime_config("deep_agent").caps().runtime_loop_limit == 16


def test_override_loop_limit():
    c = parse_agent_runtime_config({"kind": "create_agent", "runtime_loop_limit": 3})
    assert c.caps().runtime_loop_limit == 3


def test_string_form_backcompat():
    # v20 string form still parses to kind-only with default caps.
    c = parse_agent_runtime_config("create_agent")
    assert c.kind == "create_agent"
    assert c.runtime_loop_limit is None  # unset → default at caps()


def test_negative_loop_limit_rejected():
    with pytest.raises(RuntimeError, match="runtime_loop_limit"):
        parse_agent_runtime_config({"kind": "create_agent", "runtime_loop_limit": -1})


def test_negative_cost_rejected():
    with pytest.raises(RuntimeError, match="cost_cap_usd"):
        parse_agent_runtime_config({"kind": "create_agent", "cost_cap_usd": -5})


def test_sandbox_only_on_deep():
    with pytest.raises(RuntimeError, match="chỉ dùng cho deep_agent"):
        parse_agent_runtime_config({"kind": "create_agent", "sandbox": {"provider": "fake"}})


def test_sandbox_provider_allowlist():
    # local / unknown providers rejected (red-team C3 positive allowlist, at parse time).
    with pytest.raises(RuntimeError, match="không hợp lệ"):
        parse_agent_runtime_config({"kind": "deep_agent", "sandbox": {"provider": "local"}})
    with pytest.raises(RuntimeError, match="không hợp lệ"):
        parse_agent_runtime_config({"kind": "deep_agent", "sandbox": {"provider": "modal"}})
    # docker (self-hosted) + fake (test) are the allowed providers.
    assert parse_agent_runtime_config(
        {"kind": "deep_agent", "sandbox": {"provider": "docker"}}
    ).sandbox == {"provider": "docker"}


def test_deep_sandbox_valid():
    c = parse_agent_runtime_config({"kind": "deep_agent", "sandbox": {"provider": "fake"}})
    assert c.caps().sandbox == {"provider": "fake"}


def test_cost_cap_is_observability_only():
    # cost_cap parses + surfaces in caps() but is NOT claimed as enforced (red-team C4).
    c = parse_agent_runtime_config({"kind": "deep_agent", "cost_cap_usd": 4.0})
    assert c.caps().cost_cap_usd == 4.0


def test_tool_calling_uses_config_loop_limit():
    # ToolCallingRuntime.build_task threads runtime_config → caps().runtime_loop_limit.
    from src.runtime_backends.tool_calling_runtime import ToolCallingRuntime

    captured = {}
    rt = ToolCallingRuntime()

    def _fake_build(**kw):
        return "graph"

    import src.agent.team_task_graph as ttg

    orig = ttg.build_team_task_graph
    ttg.build_team_task_graph = lambda **kw: (captured.update(kw) or "graph")
    try:
        cfg = AgentRuntimeConfig(kind="create_agent", runtime_loop_limit=5)
        rt.build_task(settings=None, context=None, runtime_config=cfg, reporting_config=None)
    finally:
        ttg.build_team_task_graph = orig
    # work_override captured; the loop_limit is closed over — assert it ran without runtime_config
    # leaking into build_team_task_graph (popped).
    assert "runtime_config" not in captured
    assert "reporting_config" not in captured
    assert "work_override" in captured
