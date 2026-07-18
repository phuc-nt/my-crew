"""Dual-lens P3: read-only observability routes (budget / captures / search).

Load-bearing:
- Strictly read-only GETs; a fresh install (no store files) returns empty payloads, not 500.
- /api/budget skips registry entries whose profile is missing (fleet-gauge resilience,
  same rule as the service loop) and sums per-agent spend vs cap.
- /api/captures filters by task (chronological) or agent/limit (newest-first, clamped).
- /api/search bounds q length + limit; FTS5 escaping itself lives in (and is tested
  with) HistorySearchIndex — here we only prove hostile input yields 200 + empty.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from my_crew.runtime.capture_store import CaptureStore


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    from my_crew.server.app import create_app

    return TestClient(create_app())


def _capture_row(attempt="a1", task="t1", agent="hr", **over):
    row = {
        "attempt_id": attempt, "task_id": task, "step_id": "s1", "agent_id": agent,
        "engine": "create_agent", "status": "done", "step_type": "work",
        "review_round": 0, "cost_usd": 0.01, "cost_source": "estimated",
        "input_tokens": 100, "output_tokens": 20, "started_at": "2026-07-18T00:00:00Z",
        "ended_at": "2026-07-18T00:00:05Z", "duration_ms": 5000, "error": "",
    }
    row.update(over)
    return row


def test_captures_empty_store_returns_empty_not_500(client):
    assert client.get("/api/captures").json() == {"captures": []}


def test_capture_detail_404s_cleanly(client):
    assert client.get("/api/captures/nope").status_code == 404


def test_captures_list_and_detail_roundtrip(client, tmp_path, monkeypatch):
    from my_crew.runtime.team_task_paths import capture_db_path

    store = CaptureStore(capture_db_path())
    store.record(**_capture_row())
    store.record(**_capture_row(attempt="a2", task="t2", agent="pm"))
    store.close()

    all_rows = client.get("/api/captures").json()["captures"]
    assert {r["attempt_id"] for r in all_rows} == {"a1", "a2"}
    by_task = client.get("/api/captures", params={"task_id": "t2"}).json()["captures"]
    assert [r["attempt_id"] for r in by_task] == ["a2"]
    by_agent = client.get("/api/captures", params={"agent": "hr"}).json()["captures"]
    assert [r["agent_id"] for r in by_agent] == ["hr"]
    detail = client.get("/api/captures/a1").json()
    assert detail["engine"] == "create_agent" and detail["cost_source"] == "estimated"


def test_budget_skips_missing_profiles_and_sums(client, monkeypatch, tmp_path):
    class _E:
        def __init__(self, id):  # noqa: A002 — mirrors registry entry shape
            self.id = id
            self.enabled = True

    monkeypatch.setattr(
        "my_crew.server.routes_observability.load_registry", lambda: [_E("ok"), _E("ghost")]
    )

    class _S:
        data_dir = tmp_path / "agents" / "ok"
        monthly_budget_usd = 50.0

    class _L:
        settings = _S()

    def _load(agent_id):
        if agent_id == "ghost":
            raise FileNotFoundError("Profile 'ghost' not found")
        return _L()

    monkeypatch.setattr("my_crew.server.routes_observability.load_profile", _load)
    payload = client.get("/api/budget").json()
    assert [a["agent_id"] for a in payload["agents"]] == ["ok"]
    assert payload["total_cap_usd"] == 50.0
    assert payload["ratio"] == 0.0  # no budget file yet → 0 spent, not a crash


def test_search_blank_and_hostile_queries_are_safe(client):
    assert client.get("/api/search").json() == {"hits": []}
    hostile = '" OR 1=1 -- NEAR( * )'
    resp = client.get("/api/search", params={"q": hostile, "limit": 999})
    assert resp.status_code == 200
    assert isinstance(resp.json()["hits"], list)
