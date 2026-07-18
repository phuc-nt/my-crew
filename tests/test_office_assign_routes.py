"""v15 `/api/office/assign/*` — thin-wrapper contract: bodies map onto the assign
command's slots, errors surface as clean HTTP codes (400 validation / 409 stale hash),
and the routes stay OUT of the public prefixes (protected like every /api route).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import my_crew.agent.ops_assign_team_task as assign_mod
from my_crew.server.app import create_app


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    return TestClient(create_app())


def test_staff_endpoint_lists_assignable(monkeypatch, client):
    monkeypatch.setattr(
        "my_crew.agent.team_task_roster.assignable_staff",
        lambda: [("noi-dung", "office"), ("nghien-cuu", "office")],
    )
    r = client.get("/api/office/assign/staff")
    assert r.status_code == 200
    assert r.json() == {"staff": [{"id": "noi-dung", "domain": "office"},
                                  {"id": "nghien-cuu", "domain": "office"}]}


def test_preview_maps_slots_and_auto_confirmed_flag(monkeypatch, client):
    def _fake_preview(slots):
        slots["task_id"] = "t-1"
        slots["plan_hash"] = "h-1"
        slots["pic_id"] = "noi-dung"
        slots["auto_confirmed"] = "1"
        return "KẾ HOẠCH..."

    monkeypatch.setattr(assign_mod, "preview_assign_team_task", _fake_preview)
    r = client.post("/api/office/assign/preview", json={"brief": "@noi-dung viết bài"})
    assert r.status_code == 200
    assert r.json() == {"preview_text": "KẾ HOẠCH...", "task_id": "t-1", "plan_hash": "h-1",
                        "pic_id": "noi-dung", "auto_confirmed": True}


def test_preview_validation_error_is_400(monkeypatch, client):
    def _fake_preview(slots):
        raise ValueError("@ai-do không có trong danh sách nhân sự")

    monkeypatch.setattr(assign_mod, "preview_assign_team_task", _fake_preview)
    r = client.post("/api/office/assign/preview", json={"brief": "@ai-do x"})
    assert r.status_code == 400
    assert "@ai-do" in r.json()["detail"]
    assert client.post("/api/office/assign/preview", json={"brief": "  "}).status_code == 400


def test_confirm_stale_hash_is_409(monkeypatch, client):
    def _fake_run(slots):
        raise ValueError("kế hoạch đã thay đổi hoặc hết hạn")

    monkeypatch.setattr(assign_mod, "run_assign_team_task", _fake_run)
    r = client.post("/api/office/assign/confirm", json={"task_id": "t", "plan_hash": "h"})
    assert r.status_code == 409


def test_assign_routes_are_not_public():
    from my_crew.server.auth import _PUBLIC_PREFIXES

    assert not any(p.startswith("/api/office") for p in _PUBLIC_PREFIXES)
