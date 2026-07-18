"""M2-P6 Slice 2: RunManager concurrency + lifecycle (offline, fake sync graph).

No pytest-asyncio: each test drives the manager inside an `asyncio.run` coroutine. The
fake graph's sync `.stream` yields canned `updates` chunks (the manager runs it in a
thread) — no real LLM/MCP/network.
"""

from __future__ import annotations

import asyncio

from my_crew.server.graph_runner import Terminal
from my_crew.server.run_manager import CapReachedError, RunManager, SameThreadRunningError


class _FakeGraph:
    """Sync `stream` yields the given chunks in order (matches the real graph API,
    which is sync because of the sync SqliteSaver; the manager runs it in a thread)."""

    def __init__(self, chunks):
        self._chunks = chunks

    def stream(self, _input, *, config, stream_mode):
        yield from self._chunks


class _RaisingGraph:
    def stream(self, _input, *, config, stream_mode):
        raise RuntimeError("boom in node")


def _delivered_chunks(delivered=True):
    return [
        {"perceive": {}},
        {"analyze": {"risks": [{"x": 1}]}},
        {"compose_report": {"cost_usd": 0.01}},
        {"deliver": {"delivered": delivered, "delivery_summary": "ok"}},
    ]


def _interrupt_chunks():
    iv = type("I", (), {"value": {"summary": "external daily report → Slack C1"}})()
    return [{"perceive": {}}, {"__interrupt__": (iv,)}]


def _build(graph):
    return lambda agent_id, kind, audience, dry_run: graph


async def _drain(handle) -> list:
    """Drain a run's queue until (and including) the terminal sentinel."""
    out = []
    while True:
        item = await asyncio.wait_for(handle.queue.get(), timeout=2.0)
        out.append(item)
        if isinstance(item, Terminal):
            return out


def test_start_returns_handle_and_runs_to_terminal():
    async def _run():
        mgr = RunManager()
        h = mgr.start("acme", "daily", "internal", False, build_graph=_build(
            _FakeGraph(_delivered_chunks())))
        events = await _drain(h)
        await h.task
        return events

    events = asyncio.run(_run())
    assert isinstance(events[-1], Terminal) and events[-1].status == "delivered"
    nodes = [list(e.keys())[0] for e in events if isinstance(e, dict)]
    assert nodes == ["perceive", "analyze", "compose_report", "deliver"]


def test_not_delivered_terminal():
    async def _run():
        mgr = RunManager()
        h = mgr.start("acme", "daily", "internal", False, build_graph=_build(
            _FakeGraph(_delivered_chunks(delivered=False))))
        events = await _drain(h)
        await h.task
        return events

    assert asyncio.run(_run())[-1].status == "not_delivered"


def test_same_agent_thread_refused():
    async def _run():
        mgr = RunManager()
        mgr.start("acme", "daily", "internal", False, build_graph=_build(
            _FakeGraph(_delivered_chunks())))
        try:
            mgr.start("acme", "daily", "internal", False, build_graph=_build(
                _FakeGraph(_delivered_chunks())))
            return "no-raise"
        except SameThreadRunningError:
            return "refused"

    assert asyncio.run(_run()) == "refused"


def test_different_agents_run_concurrently_up_to_cap():
    async def _run():
        mgr = RunManager(cap=4)
        for i in range(4):
            mgr.start(f"ag{i}", "daily", "internal", False, build_graph=_build(
                _FakeGraph(_delivered_chunks())))
        try:
            mgr.start("ag4", "daily", "internal", False, build_graph=_build(
                _FakeGraph(_delivered_chunks())))
            return "no-raise"
        except CapReachedError:
            return "capped"

    assert asyncio.run(_run()) == "capped"


def test_interrupt_yields_interrupted_terminal():
    async def _run():
        mgr = RunManager()
        h = mgr.start("acme", "daily", "external", False, build_graph=_build(
            _FakeGraph(_interrupt_chunks())))
        events = await _drain(h)
        await h.task
        return events

    events = asyncio.run(_run())
    term = events[-1]
    assert term.status == "interrupted"
    assert term.thread_id == "acme:daily:external"
    assert "Slack" in term.summary
    # NO deliver chunk reached the queue (graph paused before it)
    assert not any(isinstance(e, dict) and "deliver" in e for e in events)


def test_graph_exception_yields_error_terminal_and_releases_slot():
    async def _run():
        mgr = RunManager()
        h = mgr.start("acme", "daily", "internal", False, build_graph=_build(_RaisingGraph()))
        events = await _drain(h)
        await h.task
        # slot released → can start the same thread again after the error
        h2 = mgr.start("acme", "daily", "internal", False, build_graph=_build(
            _FakeGraph(_delivered_chunks())))
        await _drain(h2)
        await h2.task
        return events

    events = asyncio.run(_run())
    assert events[-1].status == "error"
    assert "boom" in events[-1].message


class _FloodGraph:
    """Emits more chunks than the queue holds, to exercise drop-oldest back-pressure."""

    def __init__(self, n):
        self._n = n

    def stream(self, _input, *, config, stream_mode):
        for i in range(self._n):
            yield {"perceive": {"i": i}}
        yield {"deliver": {"delivered": True, "delivery_summary": "ok"}}


def test_flood_does_not_wedge_and_terminal_survives():
    # A watcher-less run that emits FAR more chunks than the queue size must not block
    # _drive (it would hold the cap slot forever) — drop-oldest keeps it flowing, the
    # run completes, and the terminal still arrives (cached on the handle too).
    async def _run():
        mgr = RunManager(ttl_s=10)
        h = mgr.start("acme", "daily", "internal", False, build_graph=_build(_FloodGraph(500)))
        await asyncio.wait_for(h.task, timeout=2.0)  # must finish, not hang
        return h

    h = asyncio.run(_run())
    assert h.status == "terminal"
    assert h.terminal.status == "delivered"  # terminal survived the flood
    assert h.queue.qsize() <= 256  # bounded


def test_no_watcher_still_completes_and_evicts():
    async def _run():
        mgr = RunManager(ttl_s=0.01)  # evict almost immediately after terminal
        h = mgr.start("acme", "daily", "internal", False, build_graph=_build(
            _FakeGraph(_delivered_chunks())))
        await h.task  # run completes without anyone draining the queue
        await asyncio.sleep(0.05)  # let the TTL eviction fire
        return mgr.get(h.run_id)

    assert asyncio.run(_run()) is None  # evicted
