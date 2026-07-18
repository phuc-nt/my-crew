"""M2-P6 Slice 3: app importable + main() binds 127.0.0.1 only (no real server)."""

from __future__ import annotations

from my_crew.server import app as app_module


def test_app_importable():
    from my_crew.server.app import app

    assert app is not None


def test_main_binds_localhost_only(monkeypatch):
    captured = {}

    def _fake_run(app, *, host, port):
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr("uvicorn.run", _fake_run)
    monkeypatch.delenv("PORT", raising=False)
    app_module.main()
    assert captured["host"] == "127.0.0.1"  # NEVER 0.0.0.0
    assert captured["port"] == 8765  # default


def test_main_honors_port_env(monkeypatch):
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, *, host, port: captured.update(port=port))
    monkeypatch.setenv("PORT", "9001")
    app_module.main()
    assert captured["port"] == 9001
