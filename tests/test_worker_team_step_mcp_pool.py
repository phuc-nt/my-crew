"""v48: a team-step runs under the MCP session pool, so every call_tool during the step (graph
run AND the in-step review, both under run_team_step) reuses one subprocess per server instead of
spawning per call. Asserts at the stable seam — `current_pool()` is non-None while run_team_step
runs — not on pool internals. Mirrors the fixture setup of test_capture_team_step_integration.
"""

from __future__ import annotations

from types import SimpleNamespace

from my_crew.config.config_builders import build_settings_from_dict
from my_crew.runtime.team_task_store import TeamTaskStore


def _fake_loaded():
    return SimpleNamespace(
        soul="", project="", memory="", company_docs=(), skills=(), domain="pm",
        web_search=False,
    )


def _plan(store: TeamTaskStore):
    steps = [{"step_id": "s1", "title": "Do it", "assigned_to": "a1", "deps": []}]
    store.create_task(task_id="t1", title="demo", original_request="pool test")
    store.set_plan("t1", steps, plan_hash="")


def test_team_step_runs_under_mcp_pool(tmp_path, monkeypatch):
    from my_crew.adapters.mcp_session_pool import current_pool
    from my_crew.runtime import team_step_runner
    from my_crew.runtime.worker import _run_team_step_kind

    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)

    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    _plan(store)
    attempt = store.reserve_step("t1", "s1")
    store.close()

    seen: dict[str, object] = {}

    def _capture_run_team_step(loaded, settings, *, task_id, step_id, attempt_id):
        # Capture whether the pool contextvar is active AT the moment the step body runs.
        seen["pool"] = current_pool()
        return {"status": team_step_runner.STATUS_DONE, "result_text": "ok", "step_title": "Do it"}

    monkeypatch.setattr(team_step_runner, "run_team_step", _capture_run_team_step)

    settings = build_settings_from_dict({"data_dir": tmp_path})
    _run_team_step_kind(
        ["--report", "team-step", "--task-id", "t1", "--step-id", "s1", "--attempt-id", attempt],
        agent_id="a1", loaded=_fake_loaded(), settings=settings,
        data_dir=tmp_path / "agents" / "a1",
    )

    assert "pool" in seen, "run_team_step was not invoked"
    assert seen["pool"] is not None, "team-step must run inside the MCP session pool (v48)"
