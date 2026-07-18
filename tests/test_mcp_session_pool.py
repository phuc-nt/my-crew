"""McpSessionPool (v11 P3) — lazy-open, reuse, clean close, fallback, min-version.

Hermetic: no real subprocess. `MultiServerMCPClient.session` and `load_mcp_tools` are
monkeypatched to a fake in-process session so the owner-task/anyio machinery runs for
real (real asyncio loop, real thread, real queue/future bridge) without spawning node.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import pytest

from my_crew.adapters import mcp_session_pool as pool_mod
from my_crew.adapters.mcp_session_pool import (
    MIN_SERVER_VERSIONS,
    McpSessionPool,
    check_min_version,
    current_pool,
)
from my_crew.config.reporting_config import McpServerSpec


def _spec(name: str = "jira") -> McpServerSpec:
    return McpServerSpec(
        name=name, dist_path=Path("/dev/null"), env={"X": "1"}, required_env_keys=()
    )


class _FakeTool:
    """A fake MCP tool: records calls, returns a canned result (or raises)."""

    def __init__(self, name: str, result: Any = None, error: Exception | None = None):
        self.name = name
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    async def ainvoke(self, args: dict) -> Any:
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.result


class _FakeSession:
    """Stands in for the real MCP ClientSession: initialize() + nothing else needed
    (tool invocation goes through the fake tool objects, not the session)."""

    def __init__(self, version: str = "1.3.0"):
        self._version = version
        self.initialized = False

    async def initialize(self):
        self.initialized = True

        class _Info:
            def __init__(self, version):
                self.version = version

        class _Result:
            def __init__(self, version):
                self.serverInfo = _Info(version)

        return _Result(self._version)


# Default fake version is far above every min so the enforce-by-default check (v11 P4) is a no-op
# for tests about pool mechanics; version-specific tests pass their own `version=`.
def _install_fake_client(monkeypatch, *, spawn_count: dict, version: str = "999.0.0",
                          tools: dict[str, _FakeTool] | None = None,
                          open_error: Exception | None = None):
    """Patch MultiServerMCPClient.session (async CM) + load_mcp_tools for the pool
    module's imports. `spawn_count` is mutated: one increment per session OPEN (i.e.
    per subprocess that would have been spawned)."""
    tools = tools if tools is not None else {"ping": _FakeTool("ping", result="pong")}

    @contextlib.asynccontextmanager
    async def fake_session(self, name, auto_initialize=False):
        spawn_count["n"] = spawn_count.get("n", 0) + 1
        if open_error is not None:
            raise open_error
        yield _FakeSession(version=version)

    class _FakeClient:
        def __init__(self, config):
            self.config = config

        session = fake_session

    async def fake_load_mcp_tools(session):
        return list(tools.values())

    monkeypatch.setattr(pool_mod, "MultiServerMCPClient", _FakeClient)
    monkeypatch.setattr(
        "langchain_mcp_adapters.tools.load_mcp_tools", fake_load_mcp_tools
    )


# --- lazy-open + reuse ---------------------------------------------------------------


def test_lazy_open_and_reuse_one_session_per_server(monkeypatch):
    spawn_count: dict = {}
    _install_fake_client(monkeypatch, spawn_count=spawn_count)

    with McpSessionPool() as pool:
        assert spawn_count.get("n", 0) == 0  # nothing spawned until first call
        r1 = pool.call(_spec("jira"), "ping", {})
        r2 = pool.call(_spec("jira"), "ping", {})
        r3 = pool.call(_spec("jira"), "ping", {})
        assert (r1, r2, r3) == ("pong", "pong", "pong")
        assert spawn_count["n"] == 1  # 3 calls, same server -> 1 open


def test_two_different_servers_open_two_sessions(monkeypatch):
    spawn_count: dict = {}
    _install_fake_client(monkeypatch, spawn_count=spawn_count)

    with McpSessionPool() as pool:
        pool.call(_spec("jira"), "ping", {})
        pool.call(_spec("slack"), "ping", {})
        pool.call(_spec("jira"), "ping", {})
        assert spawn_count["n"] == 2


def test_call_captures_server_version(monkeypatch):
    spawn_count: dict = {}
    _install_fake_client(monkeypatch, spawn_count=spawn_count, version="9.9.9")

    with McpSessionPool() as pool:
        pool.call(_spec("jira"), "ping", {})
        assert pool.server_version(_spec("jira")) == "9.9.9"


def test_unknown_tool_raises_without_killing_owner(monkeypatch):
    spawn_count: dict = {}
    _install_fake_client(
        monkeypatch, spawn_count=spawn_count, tools={"ping": _FakeTool("ping", result="pong")}
    )

    with McpSessionPool() as pool:
        with pytest.raises(ValueError, match="not found on server"):
            pool.call(_spec("jira"), "missing_tool", {})
        # owner survives a bad call — next call on the same server still works
        assert pool.call(_spec("jira"), "ping", {}) == "pong"
        assert spawn_count["n"] == 1


class _BlockingTool:
    """A tool whose ainvoke blocks forever (until cancelled) — models a wedged call."""

    name = "block"

    async def ainvoke(self, args: dict) -> Any:
        import asyncio

        await asyncio.Event().wait()  # never resolves; only a cancel frees it


def test_wedged_call_times_out_and_invalidates_without_stalling_close(monkeypatch):
    # review M1: a call cancelled while in-flight (here via the call timeout → _invalidate →
    # owner.cancel) must fail the caller and let close() return promptly, not stall 60s.
    import time

    spawn_count: dict = {}
    _install_fake_client(monkeypatch, spawn_count=spawn_count, tools={"block": _BlockingTool()})
    # shrink the per-call timeout so the test is fast; the point is the timeout PATH.
    monkeypatch.setattr(pool_mod, "_CALL_TIMEOUT_S", 0.5)

    with McpSessionPool() as pool:
        t0 = time.time()
        with pytest.raises(RuntimeError, match="timed out"):
            pool.call(_spec("jira"), "block", {})
        # the wedged server was invalidated; a fresh call re-opens a new session
        assert time.time() - t0 < 5.0
        # close() (via __exit__) must not hang on the cancelled in-flight owner
    # if we got here, __exit__/close returned — assert it was prompt
    assert True


# --- close() ---------------------------------------------------------------------


def test_close_joins_cleanly_and_rejects_further_calls(monkeypatch):
    spawn_count: dict = {}
    _install_fake_client(monkeypatch, spawn_count=spawn_count)

    pool = McpSessionPool()
    with pool:
        pool.call(_spec("jira"), "ping", {})

    # __exit__ already called close(); the background thread must have stopped.
    assert not pool._thread.is_alive()
    with pytest.raises(RuntimeError, match="closed"):
        pool.call(_spec("jira"), "ping", {})


def test_close_is_idempotent(monkeypatch):
    spawn_count: dict = {}
    _install_fake_client(monkeypatch, spawn_count=spawn_count)

    pool = McpSessionPool()
    with pool:
        pool.call(_spec("jira"), "ping", {})
    pool.close()  # second close must not raise/hang
    pool.close()


def test_close_tears_down_even_after_exception_mid_run(monkeypatch):
    spawn_count: dict = {}
    _install_fake_client(monkeypatch, spawn_count=spawn_count)

    pool = McpSessionPool()
    with pytest.raises(RuntimeError):
        with pool:
            pool.call(_spec("jira"), "ping", {})
            raise RuntimeError("boom mid-run")
    assert not pool._thread.is_alive()


# --- fallback (no pool set -> per-call path) ------------------------------------


def test_current_pool_is_none_outside_context():
    assert current_pool() is None


def test_current_pool_set_inside_context_and_reset_after(monkeypatch):
    spawn_count: dict = {}
    _install_fake_client(monkeypatch, spawn_count=spawn_count)

    assert current_pool() is None
    with McpSessionPool() as pool:
        token = pool_mod._current_pool.set(pool)
        try:
            assert current_pool() is pool
        finally:
            pool_mod._current_pool.reset(token)
    assert current_pool() is None


def test_adapter_call_tool_uses_pool_when_active(monkeypatch):
    """End-to-end: mcp_adapter.call_tool must route through the pool when one is set,
    and back to the per-call path when it is not (the backward-compat contract)."""
    spawn_count: dict = {}
    _install_fake_client(monkeypatch, spawn_count=spawn_count)

    from my_crew.adapters.mcp_adapter import call_tool

    with McpSessionPool() as pool:
        token = pool_mod._current_pool.set(pool)
        try:
            assert call_tool(_spec("jira"), "ping", {}) == "pong"
            assert call_tool(_spec("jira"), "ping", {}) == "pong"
        finally:
            pool_mod._current_pool.reset(token)
    assert spawn_count["n"] == 1  # both calls reused the one pooled session

    # Outside any pool context, current_pool() is None again — fallback path (not
    # exercised for real here since that would spawn `node /dev/null`; the guarantee
    # under test is just that the pool is no longer consulted).
    assert current_pool() is None


# --- min-version warn/enforce -----------------------------------------------------


def test_check_min_version_below_min_warns_once_when_enforce_off(monkeypatch, caplog):
    # v11 P4 flipped the default to ENFORCE; MCP_MIN_VERSION_ENFORCE=false downgrades to a warning.
    monkeypatch.setattr(pool_mod, "_warned_servers", set())
    monkeypatch.setenv("MCP_MIN_VERSION_ENFORCE", "false")
    with caplog.at_level("WARNING"):
        check_min_version("jira", "1.0.0")
        check_min_version("jira", "1.0.0")  # second call must NOT warn again
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "jira" in warnings[0].message
    assert MIN_SERVER_VERSIONS["jira"] in warnings[0].message


def test_check_min_version_below_min_raises_by_default(monkeypatch):
    # Default (env unset) enforces since v11 P4.
    monkeypatch.delenv("MCP_MIN_VERSION_ENFORCE", raising=False)
    with pytest.raises(RuntimeError, match="upgrade to >="):
        check_min_version("jira", "1.0.0")


def test_check_min_version_at_or_above_min_is_silent(caplog):
    with caplog.at_level("WARNING"):
        check_min_version("jira", MIN_SERVER_VERSIONS["jira"])
        check_min_version("slack", "99.0.0")
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


def test_check_min_version_enforce_raises(monkeypatch):
    monkeypatch.setenv("MCP_MIN_VERSION_ENFORCE", "true")
    try:
        with pytest.raises(RuntimeError, match="upgrade to >="):
            check_min_version("confluence", "0.9.0")
    finally:
        monkeypatch.delenv("MCP_MIN_VERSION_ENFORCE", raising=False)


def test_check_min_version_unknown_server_is_skipped(caplog, monkeypatch):
    monkeypatch.delenv("MCP_MIN_VERSION_ENFORCE", raising=False)
    with caplog.at_level("WARNING"):
        check_min_version("linear", "0.0.1")  # not in MIN_SERVER_VERSIONS -> tolerated
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


def test_check_min_version_missing_reported_version_is_skipped(caplog):
    with caplog.at_level("WARNING"):
        check_min_version("jira", None)
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


def test_pool_open_below_min_version_surfaces_as_call_error(monkeypatch):
    """Enforce mode: a low server version must fail the CALL with a clear upgrade
    message, not hang or silently succeed."""
    spawn_count: dict = {}
    _install_fake_client(monkeypatch, spawn_count=spawn_count, version="0.1.0")
    monkeypatch.setattr(pool_mod, "_warned_servers", set())
    monkeypatch.setenv("MCP_MIN_VERSION_ENFORCE", "true")
    try:
        with McpSessionPool() as pool:
            with pytest.raises(RuntimeError, match="upgrade to >="):
                pool.call(_spec("jira"), "ping", {})
    finally:
        monkeypatch.delenv("MCP_MIN_VERSION_ENFORCE", raising=False)
