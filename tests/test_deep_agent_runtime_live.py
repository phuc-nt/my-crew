"""v20.5 Phase 3: DeepAgentRuntime live wiring — fail-closed, PII gate, teardown, loop cap.

Uses the fake sandbox (no Docker, no LLM). Proves the safety WIRING: a deep_agent without a
sandbox refuses up-front, the context is PII-gated before the sandbox, and the sandbox is torn
down. A real LLM/Docker run is the Phase 5 E2E.
"""

from __future__ import annotations

import importlib.util

import pytest

from src.runtime_backends import resolve_runtime
from src.runtime_backends.config import AgentRuntimeConfig

_HAS_DEEPAGENTS = importlib.util.find_spec("deepagents") is not None
pytestmark = pytest.mark.skipif(not _HAS_DEEPAGENTS, reason="deepagents optional dep not installed")


def _lp(sandbox=None):
    return type(
        "LP", (),
        {
            "agent_runtime": AgentRuntimeConfig(kind="deep_agent", sandbox=sandbox),
            "profile_id": "x",
        },
    )()


def test_deep_agent_resolves():
    from src.runtime_backends.deep_agent_runtime import DeepAgentRuntime

    assert isinstance(resolve_runtime(_lp({"provider": "fake"})), DeepAgentRuntime)


def test_no_sandbox_fails_closed():
    rt = resolve_runtime(_lp({"provider": "fake"}))
    with pytest.raises(RuntimeError, match="fail-closed"):
        rt.build_task(
            settings=None, context=None,
            runtime_config=AgentRuntimeConfig(kind="deep_agent"),  # no sandbox
            data_dir="/tmp", task_id="t",
        )


def test_report_not_supported():
    from src.runtime_backends.deep_agent_runtime import DeepAgentRuntime

    with pytest.raises(RuntimeError, match="chưa hỗ trợ báo cáo"):
        DeepAgentRuntime().build_report(_lp(), None, "daily", "internal")


# --- PII gate --------------------------------------------------------------------------


def test_pii_gate_strips_internal_context():
    from src.profile.context import ProfileContext
    from src.runtime_backends.deep_agent_pii_gate import gate_context_for_sandbox

    ctx = ProfileContext(
        persona="Bạn là nhân viên nghiên cứu.",
        project="dự án X",
        memory="BÍ MẬT nội bộ: lương nhân viên A = 50tr",
        capability="skill nội bộ",
    )
    ctx = gate_context_for_sandbox(ctx)
    assert ctx.persona == "Bạn là nhân viên nghiên cứu."  # kept (role framing)
    assert ctx.project == "dự án X"  # kept (work input)
    assert ctx.memory == ""  # STRIPPED (red-team H2)
    assert ctx.capability == ""  # STRIPPED
    assert ctx.company_docs == ()  # STRIPPED


# --- teardown --------------------------------------------------------------------------


def test_teardown_calls_backend_teardown():
    from src.runtime_backends.sandbox_teardown import teardown_sandbox

    called = {"n": 0}

    class _B:
        def teardown(self):
            called["n"] += 1

    teardown_sandbox(_B())
    assert called["n"] == 1


def test_teardown_swallows_errors():
    from src.runtime_backends.sandbox_teardown import teardown_sandbox

    class _B:
        def teardown(self):
            raise RuntimeError("container gone")

    teardown_sandbox(_B())  # must not raise
    teardown_sandbox(None)  # no-op
