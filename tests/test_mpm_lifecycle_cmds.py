"""`my-crew doctor` (read-only diagnosis) + `my-crew upgrade` (mode-aware guidance)."""

from __future__ import annotations

from my_crew.entrypoints import mpm_lifecycle_cmds as life


def _quiet_env(monkeypatch, tmp_path):
    monkeypatch.setattr(life, "MY_CREW_HOME", tmp_path)
    monkeypatch.setattr(life, "load_dotenv", lambda *a, **k: None, raising=False)


def test_doctor_reports_failures_rc1(monkeypatch, tmp_path, capsys):
    _quiet_env(monkeypatch, tmp_path)
    monkeypatch.setattr(life, "_tool_version", lambda cmd: None)  # no node/npm
    monkeypatch.setattr(
        "my_crew.server.integration_health._run_checks",
        lambda: [{"id": "x", "label": "X", "ok": False, "detail": "d", "hint": "h"}],
    )
    rc = life.run_doctor([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "✗ node" in out and "✗ X" in out and "→ h" in out


def test_doctor_all_green_rc0(monkeypatch, tmp_path, capsys):
    _quiet_env(monkeypatch, tmp_path)
    monkeypatch.setattr(life, "_tool_version", lambda cmd: "v22.0.0")
    monkeypatch.setattr("my_crew.server.integration_health._run_checks", lambda: [])
    assert life.run_doctor([]) == 0
    assert "all checks passed" in capsys.readouterr().out


def test_upgrade_check_exit_codes(monkeypatch, capsys):
    monkeypatch.setattr(life, "version", lambda name: "0.1.0")
    monkeypatch.setattr(life, "_pypi_latest", lambda **k: "0.2.0")
    assert life.run_upgrade(["--check"]) == 3  # update available
    monkeypatch.setattr(life, "_pypi_latest", lambda **k: "0.1.0")
    assert life.run_upgrade(["--check"]) == 0  # up to date
    monkeypatch.setattr(life, "_pypi_latest", lambda **k: None)
    assert life.run_upgrade(["--check"]) == 1  # offline/unpublished


def test_upgrade_prints_mode_specific_path(monkeypatch, capsys):
    monkeypatch.setattr(life, "version", lambda name: "0.1.0")
    monkeypatch.setattr(life, "_pypi_latest", lambda **k: None)
    monkeypatch.setattr(life, "_is_checkout", lambda: True)
    life.run_upgrade([])
    assert "git pull && ./deploy/install.sh" in capsys.readouterr().out
    monkeypatch.setattr(life, "_is_checkout", lambda: False)
    life.run_upgrade([])
    assert "pip install -U my-crew" in capsys.readouterr().out
