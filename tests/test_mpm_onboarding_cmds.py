"""v49 onboarding CLI — `mpm quickstart` (OpenRouter-only dry-run report) + `mpm crew init`
(keepable starter crew reusing v32 create_crew). Both compose existing machinery; tests assert the
dispatch + the forced-dry-run + the idempotent-summary, not the underlying report/crew internals.
"""

from __future__ import annotations

from src.entrypoints import mpm_onboarding_cmds as onb

# --- quickstart -----------------------------------------------------------------------


def test_quickstart_without_openrouter_key_exits_nonzero(monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    rc = onb.run_quickstart([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "OPENROUTER_API_KEY" in err  # actionable hint, not a traceback


def test_quickstart_runs_default_daily_dry_run(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fake")
    seen = {}

    def _fake_run_agent(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr("src.entrypoints.mpm_run_cmd.run_agent", _fake_run_agent)
    rc = onb.run_quickstart([])
    assert rc == 0
    assert seen["argv"] == ["default", "--report", "daily", "--dry-run"]
    assert "--dry-run" in seen["argv"]  # forced — quickstart can never write externally


# --- crew init ------------------------------------------------------------------------


def test_crew_init_calls_create_crew_and_prints_summary(monkeypatch, capsys):
    monkeypatch.setattr(
        "src.server.template_create.create_crew",
        lambda: {"crew": "starter", "created": ["a", "b"], "skipped": [],
                 "failed": [], "coordinator_id": "truong-phong"},
    )
    rc = onb.run_crew("init", [])
    assert rc == 0
    out = capsys.readouterr().out
    assert "tạo mới 2" in out and "truong-phong" in out


def test_crew_init_idempotent_all_skipped(monkeypatch, capsys):
    monkeypatch.setattr(
        "src.server.template_create.create_crew",
        lambda: {"crew": "starter", "created": [], "skipped": ["a", "b"],
                 "failed": [], "coordinator_id": "truong-phong"},
    )
    rc = onb.run_crew("init", [])
    assert rc == 0
    assert "bỏ qua (đã có) 2" in capsys.readouterr().out


def test_crew_init_reports_failure_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(
        "src.server.template_create.create_crew",
        lambda: {"crew": "starter", "created": [], "skipped": [],
                 "failed": [{"role_id": "x", "error": "boom"}], "coordinator_id": ""},
    )
    rc = onb.run_crew("init", [])
    assert rc == 1  # a failed member surfaces a non-zero exit


def test_crew_unknown_subcommand_exits_nonzero(capsys):
    rc = onb.run_crew("bogus", [])
    assert rc == 2
    assert "mpm crew init" in capsys.readouterr().err
