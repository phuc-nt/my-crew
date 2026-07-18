"""v20 Phase 3: DeepAgentRuntime isolation — optional dep, fail-loud early, no app crash.

deepagents is a Beta package with shell+network capabilities (red-team C5), so this backend is
gated: the app must import without it, and a deep_agent agent must fail loud with install
guidance rather than silently exit-1 every tick (red-team FM5).
"""

from __future__ import annotations

import pytest

from my_crew.runtime_backends import resolve_runtime
from my_crew.runtime_backends.config import AgentRuntimeConfig
from my_crew.runtime_backends.deep_agent_runtime import (
    DeepAgentRuntime,
    deepagents_available,
    require_available,
)


class _LP:
    def __init__(self):
        self.agent_runtime = AgentRuntimeConfig(kind="deep_agent")
        self.profile_id = "x"


def test_app_imports_without_deepagents():
    # Importing the app / this module must not require the optional dep (isolation, C5).
    import my_crew.server.app  # noqa: F401 — the import itself is the assertion

    assert True


def test_deep_agent_resolves_runtime():
    assert isinstance(resolve_runtime(_LP()), DeepAgentRuntime)


@pytest.mark.skipif(deepagents_available(), reason="deepagents installed; missing-dep path N/A")
def test_missing_dep_fails_loud_with_guidance():
    with pytest.raises(RuntimeError, match="deepagents"):
        require_available()
    with pytest.raises(RuntimeError, match="deepagents"):
        DeepAgentRuntime().build_task(settings=None, data_dir="/tmp", task_id="t")


def test_report_not_supported():
    with pytest.raises(RuntimeError, match="chưa hỗ trợ báo cáo"):
        DeepAgentRuntime().build_report(_LP(), None, "daily", "internal")
