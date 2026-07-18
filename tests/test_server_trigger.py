"""M2-P6 Slice 2: POST /api/agents/{id}/trigger via TestClient (offline fake graph)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from my_crew.server import routes_runs, run_manager
from my_crew.server.app import create_app


class _FakeGraph:
    def stream(self, _input, *, config, stream_mode):
        yield {"perceive": {}}
        yield {"deliver": {"delivered": True, "delivery_summary": "ok"}}


def _patch(monkeypatch, ids=("acme",)):
    from my_crew.runtime.registry import RegistryEntry

    monkeypatch.setattr(
        routes_runs.agent_views, "load_registry",
        lambda: tuple(RegistryEntry(i, True) for i in ids),
    )
    # any triggered run uses a fake graph (no real profile / LLM / MCP)
    monkeypatch.setattr(run_manager, "default_build_graph", lambda *a, **k: _FakeGraph())


def _client():
    return TestClient(create_app())


def test_trigger_returns_run_id_and_thread_id(monkeypatch):
    _patch(monkeypatch)
    r = _client().post("/api/agents/acme/trigger", json={"kind": "daily"})
    assert r.status_code == 200
    body = r.json()
    assert body["thread_id"] == "acme:daily:internal"
    assert isinstance(body["run_id"], str) and body["run_id"]


def test_trigger_external_thread_id(monkeypatch):
    _patch(monkeypatch)
    r = _client().post("/api/agents/acme/trigger", json={"kind": "weekly", "audience": "external"})
    assert r.json()["thread_id"] == "acme:weekly:external"


def test_trigger_unknown_id_404(monkeypatch):
    _patch(monkeypatch, ids=("acme",))
    r = _client().post("/api/agents/ghost/trigger", json={"kind": "daily"})
    assert r.status_code == 404


def test_trigger_invalid_kind_422(monkeypatch):
    _patch(monkeypatch)
    r = _client().post("/api/agents/acme/trigger", json={"kind": "bogus"})
    assert r.status_code == 422


def test_trigger_invalid_audience_422(monkeypatch):
    # a typo'd audience must 422, NOT silently coerce to internal (Lớp B boundary).
    _patch(monkeypatch)
    r = _client().post("/api/agents/acme/trigger", json={"kind": "daily", "audience": "externl"})
    assert r.status_code == 422


class _StubManager:
    """A manager whose start() raises a chosen error — to assert the HTTP mapping.

    (The TestClient runs each request on its own loop, so a real in-flight run does
    not stay active across requests; the live concurrency rules are unit-tested in
    test_run_manager.py. Here we only verify the route maps each error to its code.)
    """

    def __init__(self, exc):
        self._exc = exc

    def start(self, *a, **k):
        raise self._exc


def _client_with_manager(monkeypatch, exc):
    _patch(monkeypatch)
    app = create_app()
    app.state.run_manager = _StubManager(exc)
    return TestClient(app)


def test_trigger_same_thread_409(monkeypatch):
    client = _client_with_manager(monkeypatch, run_manager.SameThreadRunningError("t"))
    r = client.post("/api/agents/acme/trigger", json={"kind": "daily"})
    assert r.status_code == 409


def test_trigger_over_cap_503(monkeypatch):
    client = _client_with_manager(monkeypatch, run_manager.CapReachedError("full"))
    r = client.post("/api/agents/acme/trigger", json={"kind": "daily"})
    assert r.status_code == 503
