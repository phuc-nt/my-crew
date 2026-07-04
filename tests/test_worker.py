"""Slice 2: per-agent worker entrypoint — offline (injected run_report, no MCP)."""

from __future__ import annotations

import json

from src.runtime import worker


def _fake_run(result):
    """A run_report stub that records its thread_id and returns a fixed result."""
    seen = {}

    def _run(loaded, settings, kind, audience, thread_id):
        seen["thread_id"] = thread_id
        seen["data_dir"] = settings.data_dir
        return result

    return _run, seen


def _patch_data_dir(monkeypatch, tmp_path):
    """Redirect the per-agent data dir under tmp so the worker writes nowhere real."""
    monkeypatch.setattr("src.runtime.agent_paths.DATA_DIR", tmp_path / ".data")
    # the worker also migrates on startup — point that DATA_DIR at the (empty) tmp too
    monkeypatch.setattr("src.runtime.legacy_migration.DATA_DIR", tmp_path / ".data")


def test_happy_dry_run_exit_0_and_run_event(monkeypatch, tmp_path):
    _patch_data_dir(monkeypatch, tmp_path)
    run, seen = _fake_run({"delivered": True, "cost_usd": 0.0, "delivery_summary": "dry"})
    rc = worker.main(
        ["--agent-id", "default", "--report", "daily", "--dry-run"], run_report=run
    )
    assert rc == 0
    runs = tmp_path / ".data" / "agents" / "default" / "runs.jsonl"
    line = json.loads(runs.read_text(encoding="utf-8").strip())
    assert line["agent_id"] == "default" and line["kind"] == "daily"
    assert line["audience"] == "internal" and line["status"] == "delivered"
    assert line["delivered"] is True and line["cost_usd"] == 0.0
    # the worker passed the agent-prefixed thread_id + the per-agent data dir
    assert seen["thread_id"] == "default:daily:internal"
    assert str(seen["data_dir"]).endswith("agents/default")


def test_internal_run_writes_report_summary(monkeypatch, tmp_path):
    # v8 M22: an internal delivered run stores a bounded report_summary on the run event.
    _patch_data_dir(monkeypatch, tmp_path)
    run, _ = _fake_run({"delivered": True, "cost_usd": 0.0,
                        "report_text": "<p>Sprint 80% hoàn tất, 1 blocker.</p>"})
    worker.main(["--agent-id", "default", "--report", "daily", "--dry-run"], run_report=run)
    runs = tmp_path / ".data" / "agents" / "default" / "runs.jsonl"
    line = json.loads(runs.read_text(encoding="utf-8").strip())
    assert "Sprint 80%" in line["report_summary"] and "<p>" not in line["report_summary"]


def test_external_run_omits_report_summary(monkeypatch, tmp_path):
    # external report content must NOT be persisted (it could be read into a roll-up).
    _patch_data_dir(monkeypatch, tmp_path)
    run, _ = _fake_run({"delivered": True, "cost_usd": 0.0,
                        "report_text": "stakeholder prose"})
    worker.main(["--agent-id", "default", "--report", "daily", "--audience", "external",
                 "--dry-run"], run_report=run)
    runs = tmp_path / ".data" / "agents" / "default" / "runs.jsonl"
    line = json.loads(runs.read_text(encoding="utf-8").strip())
    assert "report_summary" not in line


def test_run_without_report_text_omits_summary(monkeypatch, tmp_path):
    # backward-compat: a result lacking report_text yields an event without the field.
    _patch_data_dir(monkeypatch, tmp_path)
    run, _ = _fake_run({"delivered": True, "cost_usd": 0.0})
    worker.main(["--agent-id", "default", "--report", "daily", "--dry-run"], run_report=run)
    runs = tmp_path / ".data" / "agents" / "default" / "runs.jsonl"
    assert "report_summary" not in json.loads(runs.read_text(encoding="utf-8").strip())


def test_not_delivered_exit_1(monkeypatch, tmp_path):
    _patch_data_dir(monkeypatch, tmp_path)
    run, _ = _fake_run({"delivered": False, "cost_usd": 0.0})
    rc = worker.main(["--agent-id", "default", "--report", "okr"], run_report=run)
    assert rc == 1
    runs = tmp_path / ".data" / "agents" / "default" / "runs.jsonl"
    assert json.loads(runs.read_text(encoding="utf-8").strip())["status"] == "not_delivered"


def test_run_report_raising_exit_1_with_error_event(monkeypatch, tmp_path):
    _patch_data_dir(monkeypatch, tmp_path)

    def boom(loaded, settings, kind, audience, thread_id):
        raise RuntimeError("graph blew up")

    rc = worker.main(["--agent-id", "default", "--report", "daily"], run_report=boom)
    assert rc == 1
    runs = tmp_path / ".data" / "agents" / "default" / "runs.jsonl"
    assert json.loads(runs.read_text(encoding="utf-8").strip())["status"] == "error"


def test_bad_agent_id_exit_2_clean(monkeypatch, tmp_path, capsys):
    _patch_data_dir(monkeypatch, tmp_path)
    run, _ = _fake_run({"delivered": True})
    rc = worker.main(["--agent-id", "nope", "--report", "daily"], run_report=run)
    assert rc == 2
    assert "not found" in capsys.readouterr().err  # clean message, no traceback


def test_malformed_agent_id_exit_2(monkeypatch, tmp_path, capsys):
    _patch_data_dir(monkeypatch, tmp_path)
    run, _ = _fake_run({"delivered": True})
    rc = worker.main(["--agent-id", "../escape", "--report", "daily"], run_report=run)
    assert rc == 2
    assert "Invalid agent id" in capsys.readouterr().err


def test_missing_agent_id_exit_2(capsys):
    rc = worker.main(["--report", "daily"])
    assert rc == 2
    assert "usage:" in capsys.readouterr().err


def test_migration_invoked_at_startup(monkeypatch, tmp_path):
    _patch_data_dir(monkeypatch, tmp_path)
    calls = {"n": 0}

    def _count():
        calls["n"] += 1

    monkeypatch.setattr(worker, "migrate_legacy_data_dir", _count)
    run, _ = _fake_run({"delivered": True})
    worker.main(["--agent-id", "default", "--report", "daily"], run_report=run)
    assert calls["n"] == 1
