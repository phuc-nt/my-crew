"""Per-run MCP session pool (v11 P3) — reuse one spawned subprocess per server per run.

Background: `mcp_adapter.call_tool` spawns a fresh node subprocess for EVERY tool call
(`asyncio.run` per call). A weekly report makes 6 + N_epics such spawns. This pool keeps one
session open per server for the duration of a run, cutting that to one spawn per server.

The hard constraint (why this looks the way it does): the MCP stdio client uses `anyio` cancel
scopes that must be entered and exited in the SAME task. The graph nodes are SYNC (worker
`graph.invoke`, run_manager's `graph.stream` in `asyncio.to_thread`), so we cannot open a
session on one ad-hoc loop and close it on another. Instead the pool owns ONE background thread
running ONE event loop; each server gets ONE long-lived "owner" coroutine that opens its session
inside itself and services calls from a queue. Sync callers submit work into that loop via
`run_coroutine_threadsafe` and block on a `concurrent.futures.Future`. Open, every call, and close
all happen inside the owner task — anyio stays happy.

Leak safety (this reverses the old teardown-per-call decision): `close()` signals every owner task
to exit its `async with` (in its own task), then joins the loop thread. If the Python process dies
without `close()` (SIGKILL, launchd unload), the child's stdin pipe closes and the servers exit on
EOF (v11 P1/P2 added `process.stdin.on('end')` to all three) — verified by the P3 leak test.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from src.config.reporting_config import McpServerSpec

logger = logging.getLogger(__name__)

# Split timeouts (was one 60s covering spawn+call): a slow spawn and a slow call fail distinctly.
_SPAWN_TIMEOUT_S = 20.0
_CALL_TIMEOUT_S = 60.0

# Minimum known-good server version per MCP server name. A server NOT in this map
# (e.g. "linear" or another extra/config-driven server) is tolerated — skip the check
# entirely rather than guess a floor for a server we don't own (red-team F10).
MIN_SERVER_VERSIONS: dict[str, str] = {
    "jira": "4.2.0",
    "confluence": "1.5.0",
    "slack": "1.3.0",
}

# Env flag to turn the min-version check from warn-only into a hard block. Default is
# warn-only (P4 changes the default only after the fleet's servers are confirmed
# upgraded) — set MCP_MIN_VERSION_ENFORCE=true to raise instead of log.
_ENFORCE_ENV = "MCP_MIN_VERSION_ENFORCE"

# Warn at most once per server name per process — before P1/P2 shipped real serverInfo,
# every server reported the same low placeholder version, so warning on every call/spawn
# would be log spam. A set, not a per-pool attribute, so it throttles across pools too
# (worker runs one pool per invocation — a fresh process each time — so this is really
# "once per process", matching the spec).
_warned_servers: set[str] = set()


def _parse_version(version: str) -> tuple[int, ...] | None:
    """Best-effort numeric version tuple for comparison; None if unparseable."""
    try:
        from packaging.version import InvalidVersion, Version

        try:
            return tuple(Version(version).release)
        except InvalidVersion:
            return None
    except ImportError:
        # `packaging` not installed: fall back to a simple dotted-int compare. Any
        # non-numeric component (e.g. "1.2.0-beta") makes the version unparseable —
        # skip the check rather than guess.
        parts = version.strip().split(".")
        try:
            return tuple(int(p) for p in parts)
        except ValueError:
            return None


def check_min_version(server_name: str, reported_version: str | None) -> None:
    """Warn (default) or raise (MCP_MIN_VERSION_ENFORCE=true) when `server_name`'s
    reported version is below its configured minimum.

    No-ops when: the server isn't in `MIN_SERVER_VERSIONS` (unknown/extra server —
    tolerated, not our floor to enforce), the reported version is None (couldn't read
    serverInfo), or either version string fails to parse (don't guess).
    """
    minimum = MIN_SERVER_VERSIONS.get(server_name)
    if minimum is None or not reported_version:
        return
    have = _parse_version(reported_version)
    want = _parse_version(minimum)
    if have is None or want is None or have >= want:
        return

    message = (
        f"MCP server {server_name!r} reports version {reported_version} which is below "
        f"the minimum {minimum}; upgrade to >= {minimum}."
    )
    if os.getenv(_ENFORCE_ENV, "").strip().lower() == "true":
        raise RuntimeError(message)
    if server_name not in _warned_servers:
        _warned_servers.add(server_name)
        logger.warning(message)

# The active pool for the current run, if any. `call_tool` consults this; None ⇒ per-call spawn.
_current_pool: contextvars.ContextVar[McpSessionPool | None] = contextvars.ContextVar(
    "current_mcp_pool", default=None
)


def current_pool() -> McpSessionPool | None:
    return _current_pool.get()


@dataclass
class _Request:
    tool_name: str
    args: dict[str, Any]
    future: concurrent.futures.Future


@dataclass
class _ServerState:
    """One owner task + its inbox queue + the version read at initialize."""

    spec: McpServerSpec
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    owner: asyncio.Task | None = None
    ready: asyncio.Future | None = None  # resolves once the session is open (or fails)
    server_version: str | None = None
    tools_by_name: dict[str, Any] = field(default_factory=dict)
    in_flight: _Request | None = None  # the request currently being served (for cancel cleanup)


class McpSessionPool:
    """Owns a background loop; lazily opens one session per server, reused across a run.

    Use as a context manager around a single run:

        with McpSessionPool() as pool:
            token = _current_pool.set(pool)
            try:
                graph.invoke(...)   # call_tool inside picks up the pool
            finally:
                _current_pool.reset(token)
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="mcp-pool", daemon=True)
        self._servers: dict[str, _ServerState] = {}
        self._lock = threading.Lock()
        self._closed = False

    # ---- lifecycle -----------------------------------------------------------------------

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def __enter__(self) -> McpSessionPool:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # Ask each owner task to stop (each closes its own session in its own task), then stop
        # the loop and join the thread. Best-effort — a dead loop still releases via stdin EOF.
        fut = asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        try:
            fut.result(timeout=_SPAWN_TIMEOUT_S)
        except Exception:  # noqa: BLE001 — teardown must not raise; children die on stdin EOF
            logger.warning("mcp pool: shutdown did not complete cleanly", exc_info=True)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5.0)

    async def _shutdown(self) -> None:
        for state in list(self._servers.values()):
            if state.owner is not None:
                state.owner.cancel()
        for state in list(self._servers.values()):
            if state.owner is not None:
                try:
                    await state.owner
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

    # ---- per-server owner task -----------------------------------------------------------

    async def _owner(self, state: _ServerState) -> None:
        """Open the session (inside THIS task), initialize, then serve queued calls until
        cancelled. All session enter/use/exit happen here so anyio cancel scopes stay in-task."""
        from langchain_mcp_adapters.tools import load_mcp_tools

        client = MultiServerMCPClient(
            {
                state.spec.name: {
                    "transport": "stdio",
                    "command": "node",
                    "args": [str(state.spec.dist_path)],
                    "env": state.spec.env,
                }
            }
        )
        try:
            # auto_initialize=False so we can read the InitializeResult (serverInfo.version).
            async with client.session(state.spec.name, auto_initialize=False) as session:
                init = await session.initialize()
                state.server_version = getattr(getattr(init, "serverInfo", None), "version", None)
                check_min_version(state.spec.name, state.server_version)
                tools = await load_mcp_tools(session)
                state.tools_by_name = {t.name: t for t in tools}
                if state.ready is not None and not state.ready.done():
                    state.ready.set_result(True)

                while True:
                    req: _Request = await state.queue.get()
                    state.in_flight = req
                    await self._serve_one(state, session, req)
                    state.in_flight = None
        except asyncio.CancelledError:
            # Cancel lands while awaiting queue.get OR inside tool.ainvoke. CancelledError is a
            # BaseException, so _serve_one's `except Exception` never resolved the in-flight
            # future — do it here so a cancelled call() doesn't stall the caller for the full
            # 60s timeout (review M1). Then fail anything still queued.
            cancel_err = RuntimeError(f"MCP server {state.spec.name!r} session closed")
            if state.in_flight is not None and not state.in_flight.future.done():
                state.in_flight.future.set_exception(cancel_err)
            self._drain_failures(state, cancel_err)
            raise
        except Exception as exc:  # noqa: BLE001 — surface open/init failure to the waiter
            if state.ready is not None and not state.ready.done():
                state.ready.set_exception(exc)
            # Fail any queued requests so callers don't hang.
            self._drain_failures(state, exc)

    async def _serve_one(self, state: _ServerState, session: Any, req: _Request) -> None:
        try:
            tool = state.tools_by_name.get(req.tool_name)
            if tool is None:
                available = ", ".join(sorted(state.tools_by_name))
                raise ValueError(
                    f"MCP tool {req.tool_name!r} not found on server {state.spec.name!r}. "
                    f"Available: {available}"
                )
            result = await tool.ainvoke(req.args)
            if not req.future.done():
                req.future.set_result(result)
        except Exception as exc:  # noqa: BLE001 — one bad call must not kill the owner
            if not req.future.done():
                req.future.set_exception(exc)

    def _drain_failures(self, state: _ServerState, exc: Exception) -> None:
        while not state.queue.empty():
            try:
                req = state.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not req.future.done():
                req.future.set_exception(exc)

    # ---- sync entry ----------------------------------------------------------------------

    def _ensure_server(self, spec: McpServerSpec) -> _ServerState:
        """Get-or-create the server's owner task. The ready-future + owner task are created ON
        the pool loop (via call_soon_threadsafe) so all task/future objects belong to that loop.
        The state is published into `self._servers` only AFTER `_start` has run (owner + ready +
        queue exist), so a concurrent caller never sees a half-built state (review M2/M3)."""
        with self._lock:
            state = self._servers.get(spec.name)
            if state is not None and state.owner is not None:
                return state

        # Build the state; create its owner/ready/queue on the loop thread, then publish.
        state = _ServerState(spec=spec)
        started = threading.Event()

        def _start() -> None:
            state.ready = self._loop.create_future()
            state.queue = asyncio.Queue()
            state.owner = self._loop.create_task(self._owner(state))
            started.set()

        self._loop.call_soon_threadsafe(_start)
        if not started.wait(timeout=5.0):
            raise RuntimeError(
                f"MCP pool loop did not start the owner for {spec.name!r} within 5s."
            )
        with self._lock:
            # Another thread may have raced us; keep whichever is already published (its owner
            # is live). Ours is a spare that will be GC'd with its idle owner.
            existing = self._servers.get(spec.name)
            if existing is not None and existing.owner is not None:
                self._loop.call_soon_threadsafe(state.owner.cancel)  # drop our spare
                return existing
            self._servers[spec.name] = state
        return state

    def call(self, spec: McpServerSpec, tool_name: str, args: dict[str, Any]) -> Any:
        """Invoke a tool through the reused session. Blocks the calling (sync) thread."""
        if self._closed:
            raise RuntimeError("mcp pool is closed")
        spec.validate()
        state = self._ensure_server(spec)

        # Wait for the session to be open (spawn + initialize), bounded. Propagates an open/init
        # failure as the underlying exception so the caller sees the real cause.
        asyncio.run_coroutine_threadsafe(self._await_ready(state), self._loop).result(
            timeout=_SPAWN_TIMEOUT_S + 2.0
        )

        req = _Request(tool_name=tool_name, args=args, future=concurrent.futures.Future())
        asyncio.run_coroutine_threadsafe(state.queue.put(req), self._loop).result(timeout=5.0)
        try:
            return req.future.result(timeout=_CALL_TIMEOUT_S)
        except concurrent.futures.TimeoutError as exc:
            # The call is stuck; invalidate this server so the next call re-opens a fresh session.
            self._invalidate(state)
            raise RuntimeError(
                f"MCP server {spec.name!r} timed out after {_CALL_TIMEOUT_S:.0f}s "
                f"calling {tool_name!r}."
            ) from exc

    async def _await_ready(self, state: _ServerState) -> None:
        if state.ready is not None:
            await asyncio.wait_for(asyncio.shield(state.ready), timeout=_SPAWN_TIMEOUT_S)

    def _invalidate(self, state: _ServerState) -> None:
        """Drop a wedged server so the next call spawns a fresh session."""
        with self._lock:
            self._servers.pop(state.spec.name, None)
        if state.owner is not None:
            self._loop.call_soon_threadsafe(state.owner.cancel)

    def server_version(self, spec: McpServerSpec) -> str | None:
        """The serverInfo.version reported at initialize (None if not yet opened)."""
        state = self._servers.get(spec.name)
        return state.server_version if state else None
