"""Fleet insights routes: routing retro, tool health, engine spend — as JSON.

Load-bearing:
- Read-only GETs; a fresh install (no db, no trails) answers with empty shapes, not 500.
- /route-stats is the same aggregate the chat command renders — one source of truth.
- /tool-stats POOLS every agent's trail plus the team trail into one tally per tool,
  and an agent whose data dir cannot be resolved lands in `skipped`, not in a 500.
- /engine-costs groups the captures table by engine, costliest first, within `days`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from my_crew.audit.audit_log import AuditEntry, AuditLog
from my_crew.audit.tool_stats import READ_CALL_ACTION
from my_crew.runtime.capture_store import CaptureStore
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    monkeypatch.setattr("my_crew.runtime.agent_paths.DATA_DIR", tmp_path)
    monkeypatch.setattr("my_crew.server.routes_insights.load_registry", lambda: ())
    from my_crew.server.app import create_app

    return TestClient(create_app())


class _E:
    def __init__(self, id):
        self.id = id
        self.enabled = True


# --- route-stats ------------------------------------------------------------------------


def test_route_stats_fresh_install_is_empty_not_500(client):
    body = client.get("/api/insights/route-stats").json()
    assert body["total"] == 0
    assert body["by_mode"] == [] and body["by_failure"] == []
    assert body["dead_ends"] == 0 and body["downgrades"] == 0


def test_route_stats_counts_modes_sources_and_dead_ends(client):
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    store = TeamTaskStore(team_tasks_db_path())
    for tid, route in (
        ("t1", {"mode": "sprint", "source": "heuristic", "effort": "low"}),
        ("t2", {"mode": "sprint", "source": "downgrade", "effort": "low", "dead_end": True}),
        ("t3", {"mode": "team", "source": "ceo", "shape": "author_review"}),
    ):
        store.create_task(task_id=tid, title=f"Việc {tid}", pic_id="content")
        store.set_route(tid, route)
    store.close()

    body = client.get("/api/insights/route-stats").json()
    assert body["total"] == 3
    assert [(m["id"], m["count"]) for m in body["by_mode"]] == [("sprint", 2), ("team", 1)]
    assert body["by_mode"][0]["label"]  # Vietnamese label rides along for the web
    assert body["downgrades"] == 1
    assert body["dead_ends"] == 1
    assert body["by_effort"] == [
        {"id": "low", "label": body["by_effort"][0]["label"], "count": 2, "dead_ends": 1}
    ]
    assert [s["id"] for s in body["by_shape"]] == ["author_review"]


# --- tool-stats -------------------------------------------------------------------------


def _read_call(tool, *, verdict="allow", result="ok", elapsed=None, reason=""):
    params = {"elapsed_ms": elapsed} if elapsed is not None else {}
    return AuditEntry(action_type=READ_CALL_ACTION, tool=tool, verdict=verdict,
                      reason=reason, params=params, result_summary=result)


def test_tool_stats_fresh_install_is_empty(client):
    body = client.get("/api/insights/tool-stats").json()
    assert body == {"days": 7, "tools": [], "agents": [], "skipped": []}


def test_tool_stats_pools_every_agent_trail_with_the_team_trail(client, tmp_path, monkeypatch):
    monkeypatch.setattr("my_crew.server.routes_insights.load_registry",
                        lambda: (_E("hr"), _E("pm")))
    hr = AuditLog(tmp_path / "agents" / "hr" / "audit" / "audit.jsonl")
    pm = AuditLog(tmp_path / "agents" / "pm" / "audit" / "audit.jsonl")
    team = AuditLog(tmp_path / "audit" / "audit.jsonl")
    hr.record(_read_call("jira.issues", elapsed=100))
    pm.record(_read_call("jira.issues", result="error", elapsed=300))
    team.record(_read_call("jira.issues", verdict="deny", reason="ngoài giờ"))
    pm.record(_read_call("history.search", elapsed=10))

    body = client.get("/api/insights/tool-stats", params={"days": 30}).json()
    assert body["days"] == 30
    assert body["agents"] == ["hr", "pm"] and body["skipped"] == []
    by_tool = {t["tool"]: t for t in body["tools"]}
    jira = by_tool["jira.issues"]
    # One line for the tool across three trails — and a TRUE pooled average (200), not
    # an average of per-agent averages.
    assert (jira["total_calls"], jira["successes"], jira["failures"], jira["denied"]) == (
        3, 1, 1, 1)
    assert jira["avg_duration_ms"] == 200
    assert jira["common_errors"] == [{"reason": "ngoài giờ", "count": 1}]
    assert body["tools"][0]["tool"] == "jira.issues"  # worst first
    assert by_tool["history.search"]["failure_rate"] == 0.0


def test_tool_stats_skips_an_agent_whose_dir_cannot_resolve(client, monkeypatch):
    monkeypatch.setattr("my_crew.server.routes_insights.load_registry",
                        lambda: (_E("ok"), _E("../escape")))
    body = client.get("/api/insights/tool-stats").json()
    assert body["agents"] == ["ok"]
    assert body["skipped"] == ["../escape"]


def test_tool_stats_days_is_clamped(client):
    assert client.get("/api/insights/tool-stats", params={"days": 400}).json()["days"] == 90
    assert client.get("/api/insights/tool-stats", params={"days": -3}).json()["days"] == 0


# --- engine-costs -----------------------------------------------------------------------


def _capture(attempt, engine, *, status="done", cost=0.01, ms=1000, ts_started="2026-09-01"):
    return dict(attempt_id=attempt, task_id="t1", step_id="s1", agent_id="hr",
                engine=engine, status=status, cost_usd=cost, input_tokens=100,
                output_tokens=20, duration_ms=ms, started_at=f"{ts_started}T00:00:00Z")


def test_engine_costs_fresh_install_is_empty(client):
    body = client.get("/api/insights/engine-costs").json()
    assert body == {"days": 7, "engines": [], "total_cost_usd": 0.0, "total_calls": 0}


def test_engine_costs_groups_by_engine_costliest_first(client):
    from my_crew.runtime.team_task_paths import capture_db_path

    store = CaptureStore(capture_db_path())
    store.record(**_capture("a1", "native", cost=0.01, ms=1000))
    store.record(**_capture("a2", "native", cost=0.03, ms=3000, status="failed"))
    store.record(**_capture("a3", "create_agent", cost=0.02, ms=500))
    store.close()

    body = client.get("/api/insights/engine-costs", params={"days": 0}).json()
    assert body["days"] == 0 and body["total_calls"] == 3
    assert body["total_cost_usd"] == pytest.approx(0.06)
    assert [e["engine"] for e in body["engines"]] == ["native", "create_agent"]
    native = body["engines"][0]
    assert native["calls"] == 2 and native["failed"] == 1
    assert native["cost_usd"] == pytest.approx(0.04)
    assert native["input_tokens"] == 200 and native["output_tokens"] == 40
    assert native["avg_duration_ms"] == 2000.0


def test_engine_costs_window_uses_the_write_time(client):
    """`days` bounds on `ts` (when the row was written), so a row written now is inside
    any positive window even when its `started_at` is old."""
    from my_crew.runtime.team_task_paths import capture_db_path

    store = CaptureStore(capture_db_path())
    store.record(**_capture("a1", "native", ts_started="2020-01-01"))
    store.close()
    assert client.get("/api/insights/engine-costs", params={"days": 1}).json()["total_calls"] == 1
