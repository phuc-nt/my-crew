"""M2-P6 Slice 3: SSE /stream route + stream_run generator (offline, fake graph).

stream_run is exercised directly (driving a fake graph through the RunManager inside
one asyncio.run, then consuming the generator) — TestClient runs each request on its
own loop, so the trigger→stream live path is unit-tested here, and the route's 404 +
shape are checked via TestClient with a stub manager.
"""

from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from src.server.app import create_app
from src.server.graph_runner import Terminal
from src.server.run_manager import RunHandle, RunManager
from src.server.sse_stream import stream_run


class _FakeGraph:
    def __init__(self, chunks):
        self._chunks = chunks

    async def astream(self, _input, *, config, stream_mode):
        for c in self._chunks:
            await asyncio.sleep(0)
            yield c


def _delivered_chunks():
    return [
        {"perceive": {}},
        {"analyze": {"risks": [{"x": 1}], "persona": "SECRET"}},
        {"compose_report": {"cost_usd": 0.01, "report_text": "<h2>SECRET</h2>"}},
        {"deliver": {"delivered": True, "delivery_summary": "ok"}},
    ]


def _interrupt_chunks():
    iv = type("I", (), {"value": {"summary": "external daily → Slack C1"}})()
    return [{"perceive": {}}, {"__interrupt__": (iv,)}]


def _build(chunks):
    return lambda *a, **k: _FakeGraph(chunks)


async def _collect(handle) -> list[dict]:
    return [json.loads(frame["data"]) async for frame in stream_run(handle)]


def test_stream_happy_path_node_then_terminal():
    async def _run():
        mgr = RunManager()
        h = mgr.start("acme", "daily", "internal", False, build_graph=_build(_delivered_chunks()))
        await h.task  # let the run fill the queue
        return await _collect(h)

    events = asyncio.run(_run())
    nodes = [e for e in events if e["event"] == "node"]
    assert [e["node"] for e in nodes] == ["perceive", "analyze", "compose_report", "deliver"]
    assert events[-1] == {"event": "terminal", "status": "delivered", "data": {}}
    # PII firewall held across the whole stream
    assert "SECRET" not in json.dumps(events)


def test_stream_external_interrupt_terminal():
    async def _run():
        mgr = RunManager()
        h = mgr.start("acme", "daily", "external", False, build_graph=_build(_interrupt_chunks()))
        await h.task
        return await _collect(h)

    events = asyncio.run(_run())
    assert events[-1]["event"] == "terminal" and events[-1]["status"] == "interrupted"
    assert events[-1]["data"]["thread_id"] == "acme:daily:external"
    assert "Slack" in events[-1]["data"]["summary"]
    # NO deliver node event (graph paused before it)
    assert not any(e["event"] == "node" and e["node"] == "deliver" for e in events)


def test_stream_handles_none_delta_chunks():
    # Real astream(stream_mode="updates") yields {node: None} for nodes returning {} —
    # the generator's isinstance guard must survive it (and the firewall drops it).
    async def _run():
        mgr = RunManager()
        chunks = [{"perceive": None}, {"deliver": {"delivered": True, "delivery_summary": "x"}}]
        h = mgr.start("acme", "daily", "internal", False, build_graph=_build(chunks))
        await h.task
        return await _collect(h)

    events = asyncio.run(_run())
    assert {"event": "node", "node": "perceive", "data": {}} in events
    assert events[-1]["status"] == "delivered"


def test_concurrent_attach_to_running_run_is_refused():
    # A second concurrent live drain on a still-running run raises StreamBusyError
    # (instead of blocking forever on the single-consumer queue).
    from src.server.run_manager import StreamBusyError

    async def _run():
        h = RunHandle("r1", "acme", "acme:daily:internal", "daily", "internal")
        # simulate a run in flight (not terminal, queue empty)
        gen1 = stream_run(h)
        # prime gen1 so it claims the attach (advance to its first queue.get await)
        task1 = asyncio.ensure_future(gen1.__anext__())
        await asyncio.sleep(0)  # let gen1 claim handle.attached
        gen2 = stream_run(h)
        try:
            await gen2.__anext__()
            return "no-raise"
        except StreamBusyError:
            return "refused"
        finally:
            task1.cancel()

    assert asyncio.run(_run()) == "refused"


def test_stream_late_attach_gets_cached_terminal():
    # A handle already terminal with a drained queue → the generator replays the terminal.
    async def _run():
        h = RunHandle("r1", "acme", "acme:daily:internal", "daily", "internal")
        h.status = "terminal"
        h.terminal = Terminal(status="delivered")
        return await _collect(h)

    events = asyncio.run(_run())
    assert events == [{"event": "terminal", "status": "delivered", "data": {}}]


def test_stream_unknown_run_id_404(monkeypatch):
    client = TestClient(create_app())
    r = client.get("/api/runs/nope/stream")
    assert r.status_code == 404


def test_stream_route_returns_sse_content_type(monkeypatch):
    # A run that's already terminal streams a single terminal frame via the route.
    app = create_app()

    class _Mgr:
        def get(self, run_id):
            if run_id != "r1":
                return None
            h = RunHandle("r1", "acme", "acme:daily:internal", "daily", "internal")
            h.status = "terminal"
            h.terminal = Terminal(status="delivered")
            return h

    app.state.run_manager = _Mgr()
    with TestClient(app) as client:
        r = client.get("/api/runs/r1/stream")
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        assert '"status": "delivered"' in r.text


def test_stream_route_409_when_running_run_already_attached():
    # A running run already being streamed → second attach gets 409 (not a hang).
    app = create_app()

    class _Mgr:
        def get(self, run_id):
            h = RunHandle("r1", "acme", "acme:daily:internal", "daily", "internal")
            h.status = "running"
            h.attached = True  # a live stream already owns it
            return h

    app.state.run_manager = _Mgr()
    with TestClient(app) as client:
        assert client.get("/api/runs/r1/stream").status_code == 409
