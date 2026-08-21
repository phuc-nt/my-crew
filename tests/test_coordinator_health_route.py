"""`GET /api/health/coordinator` — v16 dispatch-liveness banner, now carrying a
platform-aware `hint` (see coordinator-health-banner.tsx) instead of a hardcoded
checkout-dev restart command."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient


def _client():
    from my_crew.server.app import create_app

    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _neutral_platform(monkeypatch):
    """Force the "generic fallback" branch so tests don't depend on the CI machine's
    actual launchd/container/systemd state."""
    monkeypatch.setattr("os.system", lambda _cmd: 1 << 8)
    monkeypatch.setattr("os.path.exists", lambda _p: False)
    monkeypatch.delenv("INVOCATION_ID", raising=False)


def test_no_coordinator_has_empty_hint(monkeypatch):
    monkeypatch.setattr(
        "my_crew.runtime.company.load_company",
        lambda: Mock(coordinator_id=None),
    )
    body = _client().get("/api/health/coordinator").json()
    assert body["reason"] == "no_coordinator"
    assert body["hint"] == ""


def test_no_heartbeat_has_nonempty_hint(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "my_crew.runtime.company.load_company",
        lambda: Mock(coordinator_id="ceo"),
    )
    monkeypatch.setattr("my_crew.config.settings.DATA_DIR", tmp_path)
    body = _client().get("/api/health/coordinator").json()
    assert body["reason"] == "no_heartbeat"
    assert body["alive"] is False
    assert "runtime.service" in body["hint"]  # generic fallback names the module path


def test_alive_has_empty_hint(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "my_crew.runtime.company.load_company",
        lambda: Mock(coordinator_id="ceo"),
    )
    monkeypatch.setattr("my_crew.config.settings.DATA_DIR", tmp_path)
    (tmp_path / "coordinator.heartbeat").write_text("", encoding="utf-8")
    body = _client().get("/api/health/coordinator").json()
    assert body["alive"] is True
    assert body["hint"] == ""


def test_container_platform_hint(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "my_crew.runtime.company.load_company",
        lambda: Mock(coordinator_id="ceo"),
    )
    monkeypatch.setattr("my_crew.config.settings.DATA_DIR", tmp_path)
    monkeypatch.setattr("os.path.exists", lambda p: p == "/.dockerenv")
    body = _client().get("/api/health/coordinator").json()
    assert "docker" in body["hint"].lower() or "podman" in body["hint"].lower()


def test_public_health_endpoint_source_still_returns_ok_only():
    """The public /health liveness probe (app.py, registered on the MODULE-level `app`
    after create_app() returns — not reachable via a fresh create_app() TestClient) must
    stay {"ok": True}: this phase adds NO hint field there. Verified by reading the
    handler's return value directly rather than over HTTP, since the module-level route
    isn't present on a fresh app instance."""
    import inspect

    from my_crew.server import app as app_module

    src = inspect.getsource(app_module.health)
    assert 'return {"ok": True}' in src
