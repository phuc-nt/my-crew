"""v20 Phase 2: ToolCallingRuntime safety — positive read-allowlist, classify shim, audience.

These tests do NOT call an LLM. They prove the toolset can never contain a write/destructive
tool (red-team C2), that every read call passes through classify (red-team C1), and that
external audience withholds internal-only reads (red-team H4). The react loop itself is
exercised in the Phase 6 E2E with a real model.
"""

from __future__ import annotations

import pytest

from src.runtime_backends import resolve_runtime
from src.runtime_backends.config import AgentRuntimeConfig
from src.runtime_backends.read_only_toolset import (
    ToolPolicyError,
    assert_read_only,
    build_read_toolset,
)
from src.runtime_backends.tool_calling_runtime import ToolCallingRuntime


class _LP:
    def __init__(self, kind="create_agent"):
        self.agent_runtime = AgentRuntimeConfig(kind=kind)
        self.profile_id = "x"


class _FakeConfig:
    """Stand-in ReportingConfig — read callables only close over it, never call in these tests."""


def test_create_agent_resolves_tool_calling_runtime():
    assert isinstance(resolve_runtime(_LP()), ToolCallingRuntime)


def test_read_toolset_is_positive_allowlist():
    tools = build_read_toolset(_FakeConfig(), audience="internal")
    # Only the known read tools — never a write/delete tool. (history.search is the
    # always-on internal history read added in v33 P5.)
    assert set(tools) == {"jira.issues", "github.prs", "linear.issues",
                          "confluence.page", "history.search"}


def test_none_config_yields_empty_toolset():
    # No reporting config ⇒ no external reads; only the internal history search stays.
    assert set(build_read_toolset(None)) == {"history.search"}


def test_external_audience_drops_internal_only_reads():
    internal = set(build_read_toolset(_FakeConfig(), audience="internal"))
    external = set(build_read_toolset(_FakeConfig(), audience="external"))
    # github.prs is public-ish; the internal-only reads are withheld externally.
    assert "confluence.page" in internal and "confluence.page" not in external
    assert "jira.issues" in internal and "jira.issues" not in external
    assert external.issubset(internal)


def test_assert_read_only_rejects_destructive():
    with pytest.raises(ToolPolicyError, match="write/destructive"):
        assert_read_only(["jira.issues", "deletePage"])
    with pytest.raises(ToolPolicyError):
        assert_read_only(["deleteIssue"])


def test_assert_read_only_rejects_pack_write_tools():
    # A pack write-handler tool name (e.g. post_message / createpage) must be rejected.
    with pytest.raises(ToolPolicyError):
        assert_read_only(["post_message"])


def test_assert_read_only_passes_reads():
    assert_read_only(["jira.issues", "github.prs", "confluence.page"])  # no raise


def test_classify_shim_runs_on_each_call(monkeypatch):
    # Every read call must pass through hard_block.classify (red-team C1 policy chokepoint).
    calls = []
    import src.actions.hard_block as hb

    real = hb.classify

    def _spy(action, **kw):
        calls.append(action.get("tool"))
        return real(action, **kw)

    monkeypatch.setattr(hb, "classify", _spy)

    # A fake read callable that records it ran only AFTER classify.
    class Cfg:
        pass

    import src.tools.github_read as gh

    monkeypatch.setattr(gh, "get_open_prs", lambda config=None: "prs")
    tools = build_read_toolset(Cfg(), audience="internal")
    tools["github.prs"]({})
    assert "github.prs" in calls  # classify was invoked for the call


def test_report_not_supported():
    with pytest.raises(RuntimeError, match="chưa hỗ trợ báo cáo"):
        ToolCallingRuntime().build_report(_LP(), None, "daily", "internal")
