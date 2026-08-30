"""`my-crew doctor` (read-only diagnosis) + `my-crew upgrade` (mode-aware guidance)."""

from __future__ import annotations

from my_crew.entrypoints import mpm_lifecycle_cmds as life


def _quiet_env(monkeypatch, tmp_path):
    monkeypatch.setattr(life, "MY_CREW_HOME", tmp_path)
    monkeypatch.setattr(life, "load_dotenv", lambda *a, **k: None, raising=False)


def test_doctor_optional_failure_does_not_fail_rc(monkeypatch, tmp_path, capsys):
    """An OPTIONAL check (e.g. Slack) failing must not fail the whole doctor run — only
    REQUIRED checks (OpenRouter, home writable) gate rc."""
    _quiet_env(monkeypatch, tmp_path)
    monkeypatch.setattr(life, "_tool_version", lambda cmd: None)  # no node/npm (optional)
    monkeypatch.setattr(
        "my_crew.server.integration_health._run_checks",
        lambda: [
            {"id": "openrouter", "label": "OpenRouter (LLM)", "ok": True, "detail": "d",
             "hint": ""},
            {"id": "slack", "label": "Slack", "ok": False, "detail": "d", "hint": "h"},
        ],
    )
    rc = life.run_doctor([])
    out = capsys.readouterr().out
    assert rc == 0  # optional failure does not fail the run
    assert "✗ node" in out and "✗ Slack" in out and "→ h" in out
    assert "Bắt buộc:" in out and "Tùy chọn:" in out
    assert "Chỉ cần OpenRouter để bắt đầu." in out


def test_doctor_required_failure_rc1(monkeypatch, tmp_path, capsys):
    _quiet_env(monkeypatch, tmp_path)
    monkeypatch.setattr(life, "_tool_version", lambda cmd: "v22.0.0")
    monkeypatch.setattr(
        "my_crew.server.integration_health._run_checks",
        lambda: [
            {"id": "openrouter", "label": "OpenRouter (LLM)", "ok": False, "detail": "chưa đặt",
             "hint": "Set OPENROUTER_API_KEY"},
        ],
    )
    rc = life.run_doctor([])
    assert rc == 1
    assert "✗ OpenRouter" in capsys.readouterr().out


def test_doctor_clean_machine_openrouter_only_rc0(monkeypatch, tmp_path, capsys):
    """Clean machine, only OPENROUTER_API_KEY set: every optional integration is
    unconfigured, but rc must be 0 (required group all green)."""
    _quiet_env(monkeypatch, tmp_path)
    monkeypatch.setattr(life, "_tool_version", lambda cmd: None)  # node/npm missing (optional)
    monkeypatch.setattr(
        "my_crew.server.integration_health._run_checks",
        lambda: [
            {"id": "openrouter", "label": "OpenRouter (LLM)", "ok": True, "detail": "đã đặt",
             "hint": ""},
            {"id": "atlassian", "label": "Atlassian", "ok": False, "detail": "chưa đặt",
             "hint": "h"},
            {"id": "slack", "label": "Slack", "ok": False, "detail": "chưa đặt", "hint": "h"},
            {"id": "github", "label": "GitHub", "ok": False, "detail": "chưa đăng nhập",
             "hint": "h"},
            {"id": "docker", "label": "Docker", "ok": False, "detail": "not running",
             "hint": "h"},
        ],
    )
    assert life.run_doctor([]) == 0
    out = capsys.readouterr().out
    assert "bắt buộc OK" in out


# --- P6: doctor's orphan agent-dir listing (read-only) ---


def test_doctor_lists_orphan_agent_dirs(monkeypatch, tmp_path, capsys):
    from my_crew.runtime.registry import RegistryEntry

    _quiet_env(monkeypatch, tmp_path)
    monkeypatch.setattr(life, "_tool_version", lambda cmd: "v1")
    monkeypatch.setattr(
        "my_crew.server.integration_health._run_checks",
        lambda: [{"id": "openrouter", "label": "OpenRouter (LLM)", "ok": True,
                  "detail": "d", "hint": ""}],
    )
    data_dir = tmp_path / "data"
    monkeypatch.setattr("my_crew.entrypoints.mpm_lifecycle_cmds.DATA_DIR", data_dir)
    (data_dir / "agents" / "kept").mkdir(parents=True)
    (data_dir / "agents" / "orphan-1").mkdir(parents=True)
    monkeypatch.setattr(
        "my_crew.runtime.registry.load_registry",
        lambda: (RegistryEntry(id="kept", enabled=True),),
    )
    life.run_doctor([])
    out = capsys.readouterr().out
    assert "Dir dữ liệu mồ côi" in out
    assert "orphan-1" in out
    assert "mpm agent purge-data orphan-1 --confirm" in out
    assert "kept" not in out.split("Dir dữ liệu mồ côi")[1]


def test_doctor_no_orphans_prints_nothing_extra(monkeypatch, tmp_path, capsys):
    from my_crew.runtime.registry import RegistryEntry

    _quiet_env(monkeypatch, tmp_path)
    monkeypatch.setattr(life, "_tool_version", lambda cmd: "v1")
    monkeypatch.setattr(
        "my_crew.server.integration_health._run_checks",
        lambda: [{"id": "openrouter", "label": "OpenRouter (LLM)", "ok": True,
                  "detail": "d", "hint": ""}],
    )
    data_dir = tmp_path / "data"
    monkeypatch.setattr("my_crew.entrypoints.mpm_lifecycle_cmds.DATA_DIR", data_dir)
    (data_dir / "agents" / "kept").mkdir(parents=True)
    monkeypatch.setattr(
        "my_crew.runtime.registry.load_registry",
        lambda: (RegistryEntry(id="kept", enabled=True),),
    )
    life.run_doctor([])
    assert "Dir dữ liệu mồ côi" not in capsys.readouterr().out


def test_doctor_no_agents_dir_is_a_noop(monkeypatch, tmp_path, capsys):
    _quiet_env(monkeypatch, tmp_path)
    monkeypatch.setattr(life, "_tool_version", lambda cmd: "v1")
    monkeypatch.setattr(
        "my_crew.server.integration_health._run_checks",
        lambda: [{"id": "openrouter", "label": "OpenRouter (LLM)", "ok": True,
                  "detail": "d", "hint": ""}],
    )
    monkeypatch.setattr("my_crew.entrypoints.mpm_lifecycle_cmds.DATA_DIR", tmp_path / "no-data")
    life.run_doctor([])
    assert "Dir dữ liệu mồ côi" not in capsys.readouterr().out


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
