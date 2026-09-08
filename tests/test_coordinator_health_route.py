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


def test_public_health_endpoint_carries_no_coordinator_hint(monkeypatch):
    """The public /health liveness probe must not leak the coordinator diagnosis: it
    answers liveness + installed version only, never `reason`/`hint`/`alive`. Checked
    over HTTP now that the route is registered inside create_app() (ahead of the SPA
    catch-all) instead of on the module-level app."""
    monkeypatch.setattr(
        "my_crew.runtime.company.load_company",
        lambda: Mock(coordinator_id=None),
    )
    body = _client().get("/health").json()
    assert body["ok"] is True
    assert isinstance(body["version"], str) and body["version"]
    assert set(body) == {"ok", "version"}
