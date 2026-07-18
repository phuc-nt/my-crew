"""v45 Phase 2: create_agent gets an in-STATE file scratch (no Docker, no shell).

The scratch is deepagents StateBackend + FilesystemMiddleware with the `execute` tool STRIPPED —
files live in graph state (ephemeral), NO host FS, NO subprocess, NO Docker, NO shell. This lets a
no-shell step (routed here in Phase 3) do compose-early report writing without a container.
"""

from __future__ import annotations

import importlib.util

import pytest

_HAS_DEEPAGENTS = importlib.util.find_spec("deepagents") is not None
pytestmark = pytest.mark.skipif(not _HAS_DEEPAGENTS, reason="deepagents optional dep not installed")


def test_scratch_middleware_has_no_execute_tool():
    """THE moat check: the scratch surface exposes file tools but NO shell-shaped tool."""
    from my_crew.runtime_backends.react_loop import _state_scratch_middleware

    mw = _state_scratch_middleware()
    names = {getattr(t, "name", "") for t in mw.tools}
    assert "execute" not in names  # no shell-shaped tool
    assert {"write_file", "read_file", "ls"} <= names  # file scratch present


def test_scratch_backend_is_not_a_sandbox_protocol():
    """StateBackend must NOT be a SandboxBackendProtocol (which would carry a real shell)."""
    from deepagents.backends.state import StateBackend
    from deepagents.middleware.filesystem import SandboxBackendProtocol

    sb = StateBackend()
    assert not isinstance(sb, SandboxBackendProtocol)
    assert not hasattr(sb, "execute")  # no shell method at all


def test_scratch_backend_touches_no_host():
    """StateBackend source uses no subprocess / host FS — files are pure graph state."""
    import inspect

    from deepagents.backends.state import StateBackend

    src = inspect.getsource(StateBackend)
    assert "subprocess" not in src
    assert "def execute" not in src


def test_readback_surfaces_md_scratch_file():
    from my_crew.runtime_backends.react_loop import _merge_state_scratch_artifacts

    result = {"files": {"report.md": {"content": "# Bao cao\nNoi dung day du", "encoding": "u"}}}
    out = _merge_state_scratch_artifacts(result, "tom tat ngan")
    assert "### Artifact: report.md" in out
    assert "Noi dung day du" in out


def test_readback_skips_when_already_in_reply():
    from my_crew.runtime_backends.react_loop import _merge_state_scratch_artifacts

    body = "# Bao cao chi tiet ABC day du"
    result = {"files": {"report.md": {"content": body, "encoding": "utf-8"}}}
    out = _merge_state_scratch_artifacts(result, body + " — da nam trong reply")
    assert "### Artifact" not in out


def test_readback_no_files_unchanged():
    from my_crew.runtime_backends.react_loop import _merge_state_scratch_artifacts

    assert _merge_state_scratch_artifacts({"files": {}}, "reply") == "reply"
    assert _merge_state_scratch_artifacts({}, "reply") == "reply"


def test_readback_skips_non_md_and_plain_string_shape():
    from my_crew.runtime_backends.react_loop import _merge_state_scratch_artifacts

    # non-.md ignored; plain-string file value also supported (shape tolerance)
    result = {"files": {"data.json": {"content": "{}", "encoding": "utf-8"},
                        "note.md": "plain string body here"}}
    out = _merge_state_scratch_artifacts(result, "reply")
    assert "data.json" not in out
    assert "plain string body here" in out  # str-valued file surfaced


def test_readback_capped():
    from my_crew.runtime_backends.react_loop import (
        _SCRATCH_MERGE_MAX_CHARS,
        _merge_state_scratch_artifacts,
    )

    big = "y" * (_SCRATCH_MERGE_MAX_CHARS + 5000)
    result = {"files": {"big.md": {"content": big, "encoding": "utf-8"}}}
    out = _merge_state_scratch_artifacts(result, "reply")
    assert len(out) <= _SCRATCH_MERGE_MAX_CHARS


def test_readback_best_effort_on_bad_shape():
    from my_crew.runtime_backends.react_loop import _merge_state_scratch_artifacts

    # unexpected shapes must never raise — reply returned unchanged
    assert _merge_state_scratch_artifacts({"files": "not-a-dict"}, "reply") == "reply"
    assert _merge_state_scratch_artifacts("not-a-dict", "reply") == "reply"
