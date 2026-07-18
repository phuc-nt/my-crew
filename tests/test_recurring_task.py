"""v6 M15b: report-task + qa-task (recurring) + tasks board API. Offline.

Load-bearing:
- report-task runs the EXISTING report graph (no new write path); qa-task runs the M11
  answer path — both through the gateway.
- A recurring task has no natural end: it runs each due tick until the deadline (CODE stop,
  shared with watch) or cancel — never forever (R1).
- Board API lists every agent's tasks and cancels an open one (idempotent for terminal).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from my_crew.config.config_builders import (
    build_reporting_config_from_dict,
    build_settings_from_dict,
)
from my_crew.profile.loader import LoadedProfile
from my_crew.runtime.task_store import TaskStore


def _loaded(tmp_path):
    config = build_reporting_config_from_dict(
        {"jira_project_key": "SCRUM", "github_repo": "acme/web", "slack_report_channel": "C_REP",
         "slack_stakeholder_channel": "", "slack_external_channels": ""}
    )
    settings = build_settings_from_dict(
        {"openrouter_api_key": "k", "data_dir": tmp_path, "dry_run": False}
    )
    return LoadedProfile(
        profile_id="pm", name="PM", enabled=True, settings=settings, config=config,
        soul="", project="", memory="", schedule={}, reports=("daily",), domain="pm",
    )


# --- recurring task check logic ---


def test_report_task_runs_the_report_graph(tmp_path, monkeypatch):
    from my_crew.runtime import recurring_task

    invoked = {}

    class _Graph:
        def invoke(self, state, config):
            invoked["ran"] = True
            return {}

    monkeypatch.setattr("my_crew.runtime.worker.build_graph_for", lambda *a, **k: _Graph())
    monkeypatch.setattr("my_crew.runtime.run_config.invoke_config", lambda tid, s: {})
    summary, cost = recurring_task.run_report_task({"kind": "daily"}, _loaded(tmp_path), None)
    assert invoked["ran"] and "daily" in summary


def test_report_task_missing_kind_raises(tmp_path):
    from my_crew.runtime.recurring_task import run_report_task

    with pytest.raises(ValueError, match="kind"):
        run_report_task({}, _loaded(tmp_path), None)


def test_qa_task_answers_via_m11_path(tmp_path, monkeypatch):
    from my_crew.runtime import recurring_task

    captured = {}

    def fake_answer(loaded, settings, *, mention, pack, gateway, llm, channel):
        captured["question"] = mention["text"]
        return type("R", (), {"status": "executed"})(), 0.002

    monkeypatch.setattr("my_crew.agent.qa_answer._answer_question", fake_answer)
    monkeypatch.setattr("my_crew.packs.registry.PackRegistry.load", lambda self, d: object())
    monkeypatch.setattr("my_crew.llm.client.LlmClient", lambda s: object())
    summary, cost = recurring_task.run_qa_task(
        {"question": "hôm nay ai quá tải?"}, _loaded(tmp_path), None, gateway=object()
    )
    assert captured["question"] == "hôm nay ai quá tải?" and cost == 0.002


def test_qa_task_missing_question_raises(tmp_path):
    from my_crew.runtime.recurring_task import run_qa_task

    with pytest.raises(ValueError, match="question"):
        run_qa_task({}, _loaded(tmp_path), None, gateway=object())


def test_qa_task_dedup_ts_is_deterministic_across_processes(tmp_path, monkeypatch):
    """The synthetic mention ts (which the M11 reply dedup keys on) must be STABLE for the
    same (agent, question, day) — builtin hash() is per-process randomized and would re-post
    the answer every restart. Assert the ts is a stable sha digest, not hash()-derived."""
    from my_crew.runtime import recurring_task

    seen = {}

    def fake_answer(loaded, settings, *, mention, pack, gateway, llm, channel):
        seen.setdefault("ts", mention["ts"])
        assert mention["ts"] == seen["ts"]  # same across calls
        return type("R", (), {"status": "executed"})(), None

    monkeypatch.setattr("my_crew.agent.qa_answer._answer_question", fake_answer)
    monkeypatch.setattr("my_crew.packs.registry.PackRegistry.load", lambda self, d: object())
    monkeypatch.setattr("my_crew.llm.client.LlmClient", lambda s: object())
    loaded = _loaded(tmp_path)
    recurring_task.run_qa_task({"question": "ai quá tải?"}, loaded, None, gateway=object())
    recurring_task.run_qa_task({"question": "ai quá tải?"}, loaded, None, gateway=object())
    assert seen["ts"].startswith("qa-task:") and "hash" not in seen["ts"]
    # different question ⇒ different ts (no cross-question dedup collision)
    seen.clear()
    recurring_task.run_qa_task({"question": "khác hẳn"}, loaded, None, gateway=object())
    first = seen["ts"]
    seen.clear()
    recurring_task.run_qa_task({"question": "ai quá tải?"}, loaded, None, gateway=object())
    assert first != seen["ts"]


# --- runner: recurring deadline stop ---


def test_recurring_task_stops_at_deadline(tmp_path, monkeypatch):
    from my_crew.runtime import task_runner

    old = (datetime.now(UTC) - timedelta(days=15)).isoformat()
    s = TaskStore(tmp_path / "tasks.sqlite3")
    # createed_at is stamped by create(); overwrite to simulate an old task via direct SQL.
    tid = s.create(kind="report", params={"kind": "daily"}, schedule="0 8 * * *")
    s._conn.execute("UPDATE tasks SET created_at = ? WHERE id = ?", (old, tid))
    s._conn.commit()
    s.close()

    posts = []
    monkeypatch.setattr(task_runner, "_post",
                        lambda gw, ld, text, *, dedup: posts.append(text) or True)
    monkeypatch.setattr("my_crew.actions.action_gateway.ActionGateway",
                        lambda *a, **k: type("G", (), {"close": lambda self: None})())
    # graph must NOT run — deadline stops first
    monkeypatch.setattr("my_crew.runtime.recurring_task.run_report_task",
                        lambda *a, **k: pytest.fail("must not run past deadline"))
    loaded = _loaded(tmp_path)
    task_runner.run_tasks(loaded, loaded.settings)
    assert any("hết hạn" in p for p in posts)
    s2 = TaskStore(tmp_path / "tasks.sqlite3")
    try:
        assert s2.get(tid).status == "done"
    finally:
        s2.close()


def test_recurring_runs_at_most_once_per_day(tmp_path, monkeypatch):
    """review M1: the service fires `tasks` hourly, but a report/qa task must recompute at
    most once per calendar day — a same-day second tick is a no-op (no LLM re-compose)."""
    from my_crew.runtime import task_runner

    s = TaskStore(tmp_path / "tasks.sqlite3")
    s.create(kind="report", params={"kind": "daily"}, schedule="0 8 * * *")
    s.close()
    runs = {"n": 0}
    monkeypatch.setattr("my_crew.runtime.recurring_task.run_report_task",
                        lambda *a, **k: runs.update(n=runs["n"] + 1) or ("ran", None))
    monkeypatch.setattr(task_runner, "_post", lambda *a, **k: True)
    monkeypatch.setattr("my_crew.actions.action_gateway.ActionGateway",
                        lambda *a, **k: type("G", (), {"close": lambda self: None})())
    loaded = _loaded(tmp_path)
    task_runner.run_tasks(loaded, loaded.settings)  # first tick today → runs
    task_runner.run_tasks(loaded, loaded.settings)  # second tick today → skipped
    task_runner.run_tasks(loaded, loaded.settings)
    assert runs["n"] == 1  # ran exactly once despite three hourly ticks


def test_runner_dispatches_report_kind(tmp_path, monkeypatch):
    from my_crew.runtime import task_runner

    s = TaskStore(tmp_path / "tasks.sqlite3")
    tid = s.create(kind="report", params={"kind": "daily"}, schedule="0 8 * * *")
    s.close()
    ran = {}
    monkeypatch.setattr("my_crew.runtime.recurring_task.run_report_task",
                        lambda p, ld, st: ran.update(kind=p["kind"]) or ("ran daily", None))
    monkeypatch.setattr(task_runner, "_post", lambda *a, **k: True)
    monkeypatch.setattr("my_crew.actions.action_gateway.ActionGateway",
                        lambda *a, **k: type("G", (), {"close": lambda self: None})())
    loaded = _loaded(tmp_path)
    out = task_runner.run_tasks(loaded, loaded.settings)
    assert ran["kind"] == "daily" and out["checked"] == 1
    s2 = TaskStore(tmp_path / "tasks.sqlite3")
    try:
        t = s2.get(tid)
        assert t.status in ("open", "running") and t.history[-1].summary == "ran daily"
    finally:
        s2.close()


# --- board API ---


def _seed(agent_dir, kind="watch", params=None):
    s = TaskStore(agent_dir / "tasks.sqlite3")
    tid = s.create(kind=kind, params=params or {"target": "pr", "number": 5},
                   schedule="0 8 * * *")
    s.close()
    return tid


def _client(monkeypatch, tmp_path, ids=("pm",)):
    from my_crew.runtime import registry
    from my_crew.runtime.registry import RegistryEntry
    from my_crew.server import routes_tasks
    from my_crew.server.app import create_app

    monkeypatch.setattr("my_crew.runtime.agent_paths.DATA_DIR", tmp_path)
    monkeypatch.setattr(routes_tasks, "load_registry",
                        lambda: tuple(RegistryEntry(i, True) for i in ids))
    _ = registry  # keep import
    return TestClient(create_app())


def test_board_lists_tasks(monkeypatch, tmp_path):
    from my_crew.runtime.agent_paths import agent_data_dir

    client = _client(monkeypatch, tmp_path)
    (agent_data_dir("pm")).mkdir(parents=True, exist_ok=True)
    _seed(agent_data_dir("pm"))
    r = client.get("/api/tasks")
    assert r.status_code == 200
    agents = r.json()["agents"]
    assert len(agents) == 1 and agents[0]["agent_id"] == "pm"
    assert agents[0]["tasks"][0]["kind"] == "watch"


def test_board_cancel_open_task(monkeypatch, tmp_path):
    from my_crew.runtime.agent_paths import agent_data_dir

    client = _client(monkeypatch, tmp_path)
    (agent_data_dir("pm")).mkdir(parents=True, exist_ok=True)
    tid = _seed(agent_data_dir("pm"))
    r = client.post(f"/api/tasks/pm/{tid}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    # idempotent: cancelling again returns the terminal status unchanged
    r2 = client.post(f"/api/tasks/pm/{tid}/cancel")
    assert r2.json()["status"] == "cancelled"


def test_board_cancel_unknown_task_404(monkeypatch, tmp_path):
    from my_crew.runtime.agent_paths import agent_data_dir

    client = _client(monkeypatch, tmp_path)
    (agent_data_dir("pm")).mkdir(parents=True, exist_ok=True)
    _seed(agent_data_dir("pm"))
    assert client.post("/api/tasks/pm/999/cancel").status_code == 404


def test_board_cancel_invalid_agent_id_400(monkeypatch, tmp_path):
    """review L3: the path-escape guard rejects a malformed agent id with 400, before disk."""
    client = _client(monkeypatch, tmp_path)
    # An uppercase id violates the [a-z0-9_-] rule → 400 before any disk access.
    assert client.post("/api/tasks/BADID/1/cancel").status_code == 400


def test_qa_task_reply_posts_top_level_not_a_fake_thread(tmp_path, monkeypatch):
    """review M2: a qa-task's synthetic mention has no real Slack ts, so the reply must post
    TOP-LEVEL — a fabricated thread_ts would make Slack reject/misroute it. Drive the REAL
    _post_reply path (only the gateway.execute is stubbed) and assert no thread_ts is sent."""
    from my_crew.agent import qa_answer

    posted = {}

    class _Gw:
        def execute(self, action, *, handler, rationale):
            posted["args"] = action["args"]
            return type("R", (), {"status": "executed", "summary": "ok"})()

    loaded = _loaded(tmp_path)
    monkeypatch.setattr(qa_answer, "make_slack_post_handler", lambda server: (lambda a: "ok"))
    mention = {"ts": "qa-task:abc:2026-07-04", "text": "q", "channel": "C_REP",
               "user": "task", "synthetic": True}
    qa_answer._post_reply(_Gw(), loaded, mention, "C_REP", "câu trả lời")
    assert "thread_ts" not in posted["args"]  # top-level, no fabricated ts
    assert posted["args"]["channel"] == "C_REP"
