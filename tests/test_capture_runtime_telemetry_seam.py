"""The telemetry side-channel must thread through every engine's build_task without error.

The collector rides as a `telemetry=` kwarg down build_task → build_team_task_graph. Because
build_team_task_graph has no **kwargs, an engine that forgot to accept/pop the kwarg would
raise TypeError at graph-build for real work — a failure the happy-path tests (which inject
`deps` directly and bypass the seam) would never catch. This asserts all three engines build
a task graph with a real collector present.
"""

from __future__ import annotations

import importlib.util

import pytest

from src.config.config_builders import build_settings_from_dict
from src.runtime.step_telemetry import StepTelemetry
from src.runtime_backends import resolve_runtime
from src.runtime_backends.config import AgentRuntimeConfig


class _LoadedProfile:
    def __init__(self, kind, sandbox=None):
        self.agent_runtime = AgentRuntimeConfig(kind=kind, sandbox=sandbox)
        self.profile_id = "x"


def _build_kwargs():
    return dict(
        settings=build_settings_from_dict({}),
        context=None,
        step_title="Do the thing",
        data_dir="/tmp/telemetry-seam",
        task_id="t1",
        step_seq=1,
        step_deps=(),
        self_id="agent-x",
        telemetry=StepTelemetry(),
        # Production always passes remember_node too; the langchain runtimes do NOT pop it, so it
        # must ride **kwargs into build_team_task_graph without a TypeError. None is a valid value.
        remember_node=None,
    )


def test_native_build_task_accepts_telemetry():
    rt = resolve_runtime(_LoadedProfile("native"))
    graph = rt.build_task(**_build_kwargs())
    assert graph is not None  # built without TypeError on the telemetry kwarg


def test_create_agent_build_task_accepts_telemetry():
    rt = resolve_runtime(_LoadedProfile("create_agent"))
    graph = rt.build_task(runtime_config=AgentRuntimeConfig(kind="create_agent"), **_build_kwargs())
    assert graph is not None


@pytest.mark.skipif(
    importlib.util.find_spec("deepagents") is None, reason="deepagents optional dep not installed"
)
def test_deep_agent_build_task_accepts_telemetry():
    rt = resolve_runtime(_LoadedProfile("deep_agent", sandbox={"provider": "fake"}))
    graph = rt.build_task(
        runtime_config=AgentRuntimeConfig(kind="deep_agent", sandbox={"provider": "fake"}),
        **_build_kwargs(),
    )
    assert graph is not None
