"""v20 Phase 1: AgentRuntime seam — resolver, kill-switch, None-guard, config parse, guard.

The byte-identical guarantee is that NativeGraphRuntime delegates to the unchanged builders;
here we assert the seam's control flow (which backend, when it raises, the report guard). The
existing team-step / report suites cover that the delegated graphs still behave.
"""

from __future__ import annotations

import textwrap

import pytest

from my_crew.profile.loader import load_profile
from my_crew.runtime_backends import resolve_runtime
from my_crew.runtime_backends.config import AgentRuntimeConfig, parse_agent_runtime_config
from my_crew.runtime_backends.native_graph_runtime import NativeGraphRuntime
from my_crew.runtime_backends.protocol import runtime_kind_for


class _LP:
    def __init__(self, kind):
        self.agent_runtime = AgentRuntimeConfig(kind=kind)
        self.profile_id = "x"


# --- parse ---------------------------------------------------------------------------


def test_absent_defaults_native():
    assert parse_agent_runtime_config(None).kind == "native"
    assert parse_agent_runtime_config({}).kind == "native"
    assert parse_agent_runtime_config("").kind == "native"


def test_string_and_mapping_forms():
    assert parse_agent_runtime_config("create_agent").kind == "create_agent"
    assert parse_agent_runtime_config({"kind": "deep_agent"}).kind == "deep_agent"


def test_unknown_kind_raises_runtimeerror():
    with pytest.raises(RuntimeError, match="unknown kind"):
        parse_agent_runtime_config("gpt")


def test_bad_type_raises_runtimeerror():
    with pytest.raises(RuntimeError, match="string or a mapping"):
        parse_agent_runtime_config(["native"])


# --- resolve_runtime -----------------------------------------------------------------


def test_none_resolves_native():
    assert isinstance(resolve_runtime(None), NativeGraphRuntime)


def test_native_resolves_native():
    assert isinstance(resolve_runtime(_LP("native")), NativeGraphRuntime)


def test_create_agent_resolves_tool_calling_runtime():
    # Phase 2 landed: create_agent now resolves to ToolCallingRuntime (was deferred in Phase 1).
    from my_crew.runtime_backends.tool_calling_runtime import ToolCallingRuntime

    assert isinstance(resolve_runtime(_LP("create_agent")), ToolCallingRuntime)


def test_deep_agent_resolves_deep_runtime():
    # Phase 3 landed: deep_agent resolves to DeepAgentRuntime (gated by optional dep at build).
    from my_crew.runtime_backends.deep_agent_runtime import DeepAgentRuntime

    assert isinstance(resolve_runtime(_LP("deep_agent")), DeepAgentRuntime)


def test_deep_agent_build_task_tolerates_full_extra_kwargs():
    """Regression (v43): the step runner threads gws_context + deep_team into every non-native
    runtime's build_task. DeepAgentRuntime must POP both, not leak them into build_team_task_graph
    (which has a fixed signature and would TypeError). Pre-v43 this leaked `gws_context` — a real
    deep_agent team-step crashed. We assert build_task gets past the pop/validate and fails ONLY at
    the sandbox provider check (a clean, expected failure) rather than on an unexpected-kwarg error.
    """
    import importlib.util

    if importlib.util.find_spec("deepagents") is None:
        import pytest as _pytest

        _pytest.skip("deepagents optional dep not installed")

    from my_crew.runtime_backends.config import AgentRuntimeConfig
    from my_crew.runtime_backends.deep_agent_runtime import DeepAgentRuntime

    # No sandbox → the provider check raises RuntimeError. The point: it must reach that check,
    # not raise TypeError on gws_context/deep_team first.
    with pytest.raises(RuntimeError, match="sandbox provider"):
        DeepAgentRuntime().build_task(
            settings=None, context=None, step_title="t", data_dir="/tmp", task_id="x",
            step_seq=1, step_deps=(), search_hook=None, self_id="a", telemetry=None,
            remember_node=None, reporting_config=None,
            runtime_config=AgentRuntimeConfig(kind="deep_agent"),
            academic_search=False, gws_context=False, deep_team=True, allow_split=False,
        )


def test_force_native_killswitch(monkeypatch):
    monkeypatch.setenv("RUNTIME_FORCE_NATIVE", "1")
    # create_agent would raise, but the kill-switch forces native fleet-wide.
    assert isinstance(resolve_runtime(_LP("create_agent")), NativeGraphRuntime)
    assert runtime_kind_for(_LP("create_agent")) == "native"


def test_runtime_kind_for_none():
    assert runtime_kind_for(None) == "native"


# --- loader threads agent_runtime (separate from infra `runtime:`) -------------------


def test_loader_parses_agent_runtime(tmp_path):
    d = tmp_path / "a1"
    d.mkdir()
    (d / "profile.yaml").write_text(
        textwrap.dedent("name: A1\nagent_runtime: create_agent\n"), encoding="utf-8"
    )
    loaded = load_profile("a1", profiles_dir=tmp_path, data_dir=tmp_path / ".data")
    assert loaded.agent_runtime.kind == "create_agent"


def test_loader_infra_runtime_block_not_confused(tmp_path):
    # An infra `runtime:` block (checkpointer/store) must NOT be read as the loop selector;
    # agent_runtime stays native when only the infra block is present.
    d = tmp_path / "a2"
    d.mkdir()
    (d / "profile.yaml").write_text(
        textwrap.dedent("name: A2\nruntime:\n  checkpointer: sqlite\n  store: memory\n"),
        encoding="utf-8",
    )
    loaded = load_profile("a2", profiles_dir=tmp_path, data_dir=tmp_path / ".data")
    assert loaded.agent_runtime.kind == "native"


def test_report_guard_fails_loud_for_non_native(tmp_path):
    # A non-native agent hitting the report path must fail loud, not silently run native.
    from my_crew.runtime.worker import build_graph_for

    d = tmp_path / "a3"
    d.mkdir()
    (d / "profile.yaml").write_text("name: A3\nagent_runtime: create_agent\n", encoding="utf-8")
    loaded = load_profile("a3", profiles_dir=tmp_path, data_dir=tmp_path / ".data")
    with pytest.raises(RuntimeError, match="chưa hỗ trợ cho báo cáo"):
        build_graph_for(loaded, loaded.settings, "daily", "internal")
