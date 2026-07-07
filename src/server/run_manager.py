"""In-process run manager for on-demand triggered graph runs (v2 M2-P6).

One `RunManager` per app process. `start()` kicks a report graph off in an asyncio
background task and streams its per-node events into the run's queue; the SSE route
(Slice 3) drains that queue. Scheduled runs still go through the worker subprocess —
this is only the on-demand + observe surface.

CONCURRENCY (single event loop): `start` does its check-then-register with NO `await`
between reading `_active` and inserting, so on the one loop it is atomic — no lock
needed. Rules: same (agent, thread_id) already running → refused (409); global active
count at the cap (default 4) → refused (503); different agents run concurrently.

LIFECYCLE: `_drive` ALWAYS pushes exactly one terminal sentinel (finally-guaranteed),
so a watcher never hangs and a watcher-less run still completes + self-evicts. Node
chunks are enqueued NON-blocking (drop-oldest when the bounded queue is full), so a
slow or absent reader can never wedge `_drive` and hold its cap slot — the terminal
still gets through and the slot is released. Memory is bounded by the queue size.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from src.runtime.agent_paths import agent_thread_id
from src.runtime.run_config import invoke_config_env
from src.server.graph_runner import (
    Terminal,
    default_build_graph,
    terminal_for_delivery,
    terminal_for_interrupt,
)

logger = logging.getLogger(__name__)

_CAP = 4  # matches the scheduler's per-process cap (service.py)
_QUEUE_MAX = 256  # bound worst-case memory if nobody drains
_TTL_S = 300.0  # evict a run this long after its terminal


class SameThreadRunningError(RuntimeError):
    """A run for the same (agent, thread_id) is already active (→ 409)."""


class CapReachedError(RuntimeError):
    """The global active-run cap is reached (→ 503)."""


class StreamBusyError(RuntimeError):
    """A live stream is already draining this still-running run (→ 409).

    Single-drain (M2 single-operator): only one stream owns the queue while the run
    is in flight, so a second concurrent attach can't block forever competing for the
    one terminal. Attaching AFTER the run is terminal is always allowed (cache replay).
    """


@dataclass
class RunHandle:
    """Live handle for one in-flight run. Mutable — it carries a running task."""

    run_id: str
    agent_id: str
    thread_id: str
    kind: str
    audience: str
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=_QUEUE_MAX))
    status: str = "running"  # running | terminal
    terminal: Terminal | None = None  # cached for late watchers
    task: asyncio.Task | None = None
    # Single-drain: one live stream owns the queue at a time (M2 single-operator). A
    # second concurrent attach is refused so it cannot block forever competing for the
    # one terminal sentinel. A late attach AFTER terminal still replays the cache.
    attached: bool = False


class RunManager:
    """Holds the active runs for the process. One instance per app."""

    def __init__(self, *, cap: int = _CAP, ttl_s: float = _TTL_S) -> None:
        self._runs: dict[str, RunHandle] = {}
        self._active: set[tuple[str, str]] = set()  # (agent_id, thread_id)
        self._cap = cap
        self._ttl_s = ttl_s

    def get(self, run_id: str) -> RunHandle | None:
        return self._runs.get(run_id)

    def start(
        self,
        agent_id: str,
        kind: str,
        audience: str,
        dry_run: bool,
        *,
        build_graph=None,
        run_id: str | None = None,
    ) -> RunHandle:
        """Register + launch a run. Raises Same/CapReached before any task is created.

        `build_graph` defaults to the real per-agent builder, resolved at call time so
        a test can patch `graph_runner.default_build_graph`.
        """
        if build_graph is None:
            build_graph = default_build_graph
        thread_id = agent_thread_id(agent_id, kind, audience)
        key = (agent_id, thread_id)
        if key in self._active:
            raise SameThreadRunningError(thread_id)
        if len(self._active) >= self._cap:
            raise CapReachedError(f"active runs at cap {self._cap}")

        handle = RunHandle(
            run_id=run_id or uuid.uuid4().hex,
            agent_id=agent_id,
            thread_id=thread_id,
            kind=kind,
            audience=audience,
        )
        self._runs[handle.run_id] = handle
        self._active.add(key)
        handle.task = asyncio.create_task(self._drive(handle, build_graph, dry_run))
        return handle

    async def _drive(self, handle: RunHandle, build_graph, dry_run: bool) -> None:
        """Run the graph in a thread, stream node chunks, push exactly one terminal.

        The graph's nodes (MCP + LLM) are SYNC and its checkpointer is a sync saver
        (`SqliteSaver` by default, `PostgresSaver` when opted in — both sync; shared
        with the worker / `mpm agent resume`, so the interrupt checkpoint stays
        resume-compatible). `graph.astream` would reject the sync saver, so we run the
        SYNC `graph.stream` in `asyncio.to_thread` and bridge each chunk back to the
        event-loop queue thread-safely — keeping the loop free.
        """
        loop = asyncio.get_running_loop()
        terminal_box: dict[str, Terminal] = {}

        def _run_sync() -> None:
            # v11 P3: wrap the sync graph.stream loop in a per-run MCP session pool. This
            # runs inside `asyncio.to_thread` (its own worker thread, separate from the
            # pool's own background thread+loop) — the contextvar is set HERE, on the
            # thread that will actually call `call_tool` while streaming the graph, which
            # is what the pool's owner-task/anyio design requires.
            from src.adapters.mcp_session_pool import McpSessionPool, _current_pool

            cfg = invoke_config_env(handle.thread_id)
            last_delta: dict | None = None
            graph = build_graph(handle.agent_id, handle.kind, handle.audience, dry_run)
            terminal = terminal_for_delivery(None)  # default if no deliver chunk seen
            with McpSessionPool() as pool:
                token = _current_pool.set(pool)
                try:
                    for chunk in graph.stream({}, config=cfg, stream_mode="updates"):
                        if "__interrupt__" in chunk:
                            terminal = terminal_for_interrupt(handle.thread_id, chunk)
                            break
                        loop.call_soon_threadsafe(_put_nonblocking, handle.queue, chunk)
                        if "deliver" in chunk:
                            last_delta = chunk["deliver"]
                    else:
                        terminal = terminal_for_delivery(last_delta)
                finally:
                    _current_pool.reset(token)
            terminal_box["t"] = terminal

        try:
            await asyncio.to_thread(_run_sync)
            terminal = terminal_box["t"]
        except Exception as exc:  # noqa: BLE001 — isolate: a graph crash must not kill the loop
            logger.exception("run %s (%s) failed", handle.run_id, handle.thread_id)
            terminal = Terminal(status="error", message=str(exc)[:200])
        finally:
            handle.status = "terminal"
            handle.terminal = terminal
            # Terminal goes in non-blocking too — it is also cached on the handle for a
            # late watcher, so even if the queue is full the terminal is never lost.
            _put_nonblocking(handle.queue, terminal)
            self._schedule_evict(handle)

    def _schedule_evict(self, handle: RunHandle) -> None:
        self._active.discard((handle.agent_id, handle.thread_id))
        loop = asyncio.get_running_loop()
        loop.call_later(self._ttl_s, self._evict, handle.run_id)

    def _evict(self, run_id: str) -> None:
        """Drop a finished run. Idempotent."""
        self._runs.pop(run_id, None)


def _put_nonblocking(queue: asyncio.Queue, item) -> None:
    """Enqueue without ever blocking the producer.

    If the bounded queue is full (a slow/absent reader), drop the OLDEST buffered
    item to make room — so `_drive` never wedges on back-pressure and its slot is
    always released. A reader that can't keep up loses intermediate node events but
    still receives the terminal (also cached on the handle).
    """
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()  # drop oldest
        except asyncio.QueueEmpty:
            pass
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            pass
