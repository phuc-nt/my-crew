"""v39 #2: SMTP surfaced in the Connections screen — card + health check + writable keys.

The email/send_message-email feature needed SMTP config, but the Connections screen had no
SMTP card, so a CEO couldn't see or set it. These tests prove the card exists, presence
reflects SMTP_HOST, and the keys are writable through the whitelisted path.
"""

from __future__ import annotations


def test_smtp_card_in_catalog():
    from src.server import routes_connections

    card = next((c for c in routes_connections._CATALOG if c["id"] == "smtp"), None)
    assert card is not None
    assert "SMTP_HOST" in card["keys"] and "SMTP_PASSWORD" in card["keys"]


def test_smtp_keys_are_wizard_writable():
    # The import-time assert in routes_connections already enforces this, but pin it:
    from src.server.env_writer import SETUP_WRITABLE_KEYS

    for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
              "SMTP_FROM_ADDR", "SMTP_USE_TLS", "SMTP_RECIPIENTS"):
        assert k in SETUP_WRITABLE_KEYS


def test_smtp_health_check_reflects_host(monkeypatch):
    from src.server.integration_health import _smtp_check

    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert _smtp_check()["ok"] is False
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    ok = _smtp_check()
    assert ok["ok"] is True and ok["id"] == "smtp"


def test_smtp_check_in_run_checks(monkeypatch):
    from src.server import integration_health

    ids = {c["id"] for c in integration_health._run_checks()}
    assert "smtp" in ids


def test_smtp_check_never_leaks_value(monkeypatch):
    from src.server.integration_health import _smtp_check

    monkeypatch.setenv("SMTP_HOST", "secret-host.internal")
    monkeypatch.setenv("SMTP_PASSWORD", "super-secret-pw")
    out = _smtp_check()
    # present-only: neither the host value nor the password appears in the detail/hint.
    blob = out["detail"] + out["hint"]
    assert "secret-host.internal" not in blob and "super-secret-pw" not in blob
