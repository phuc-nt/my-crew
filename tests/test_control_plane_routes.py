"""`/api/control-plane/*` — HTTP contract for callers outside the SPA.

Load-bearing:
- `/delegate` 2-step (default) vs 1-step (`confirm: true`) both wrap the SAME
  preview/confirm functions the SPA composer uses — hash-bind stays intact.
- `/tasks/{id}` 404s on an unknown task; shapes the unified status otherwise.
- `/overview` always returns the 4 blocks with `v: 1`.
- The router is NOT in the public auth allowlist (protected like every /api route).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import my_crew.agent.ops_assign_team_task as assign_mod


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    from my_crew.server.app import create_app

    return TestClient(create_app())


class TestDelegate:
    def test_missing_brief_is_400(self, client):
        r = client.post("/api/control-plane/delegate", json={})
        assert r.status_code == 400

    def test_brief_too_long_is_400(self, client):
        r = client.post("/api/control-plane/delegate", json={"brief": "x" * 4001})
        assert r.status_code == 400

    def test_two_step_default_returns_preview_without_confirming(self, monkeypatch, client):
        def _fake_preview(slots):
            slots["task_id"] = "t-1"
            slots["plan_hash"] = "h-1"
            slots["route_mode"] = "sprint"
            return "KẾ HOẠCH..."

        monkeypatch.setattr(assign_mod, "preview_assign_team_task", _fake_preview)
        monkeypatch.setattr(
            assign_mod, "run_assign_team_task",
            lambda slots: (_ for _ in ()).throw(AssertionError("must not auto-confirm")),
        )
        r = client.post("/api/control-plane/delegate", json={"brief": "viết báo cáo"})
        assert r.status_code == 200
        body = r.json()
        assert body == {
            "v": 1, "task_id": "t-1", "plan_hash": "h-1",
            "preview_text": "KẾ HOẠCH...", "confirmed": False, "route_mode": "sprint",
        }

    def test_two_step_confirm_call_dispatches(self, monkeypatch, client):
        monkeypatch.setattr(
            assign_mod, "run_assign_team_task",
            lambda slots: f"Đã giao việc #{slots['task_id']}",
        )
        r = client.post(
            "/api/control-plane/delegate",
            json={"task_id": "t-1", "plan_hash": "h-1", "confirm": True},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["confirmed"] is True
        assert body["task_id"] == "t-1"
        assert "Đã giao việc" in body["text"]

    def test_confirm_missing_plan_hash_is_400(self, client):
        r = client.post("/api/control-plane/delegate", json={"task_id": "t-1"})
        assert r.status_code == 400

    def test_confirm_stale_hash_is_409(self, monkeypatch, client):
        def _fake_run(slots):
            raise ValueError("kế hoạch đã thay đổi hoặc hết hạn")

        monkeypatch.setattr(assign_mod, "run_assign_team_task", _fake_run)
        r = client.post(
            "/api/control-plane/delegate",
            json={"task_id": "t-1", "plan_hash": "stale", "confirm": True},
        )
        assert r.status_code == 409

    def test_one_step_confirm_true_previews_then_confirms(self, monkeypatch, client):
        def _fake_preview(slots):
            slots["task_id"] = "t-2"
            slots["plan_hash"] = "h-2"
            return "KẾ HOẠCH..."

        confirmed_calls = []

        def _fake_run(slots):
            confirmed_calls.append(slots)
            return "Đã giao việc #t-2"

        monkeypatch.setattr(assign_mod, "preview_assign_team_task", _fake_preview)
        monkeypatch.setattr(assign_mod, "run_assign_team_task", _fake_run)
        r = client.post(
            "/api/control-plane/delegate",
            json={"brief": "viết báo cáo", "confirm": True},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["confirmed"] is True
        assert body["task_id"] == "t-2"
        assert body["text"] == "Đã giao việc #t-2"
        assert confirmed_calls == [{"task_id": "t-2", "plan_hash": "h-2"}]

    def test_one_step_respects_company_auto_confirm_without_double_confirming(
        self, monkeypatch, client,
    ):
        """When `preview_assign_team_task` itself already auto-confirmed (company-wide
        autopilot flag), this route must NOT call `run_assign_team_task` again —
        that would double-dispatch the same task."""
        def _fake_preview(slots):
            slots["task_id"] = "t-3"
            slots["plan_hash"] = "h-3"
            slots["auto_confirmed"] = "1"
            return "KẾ HOẠCH...\nĐÃ TỰ XÁC NHẬN"

        monkeypatch.setattr(assign_mod, "preview_assign_team_task", _fake_preview)
        monkeypatch.setattr(
            assign_mod, "run_assign_team_task",
            lambda slots: (_ for _ in ()).throw(AssertionError("must not double-confirm")),
        )
        r = client.post(
            "/api/control-plane/delegate",
            json={"brief": "viết báo cáo", "confirm": True},
        )
        assert r.status_code == 200
        assert r.json()["confirmed"] is True

    def test_preview_validation_error_is_400(self, monkeypatch, client):
        def _fake_preview(slots):
            raise ValueError("chưa có đường báo tin")

        monkeypatch.setattr(assign_mod, "preview_assign_team_task", _fake_preview)
        r = client.post("/api/control-plane/delegate", json={"brief": "việc gì đó"})
        assert r.status_code == 400

    def test_delegate_audit_row_tagged_control_plane_api(self, monkeypatch, client, tmp_path):
        monkeypatch.setattr(
            assign_mod, "run_assign_team_task",
            lambda slots: f"Đã giao việc #{slots['task_id']}",
        )
        r = client.post(
            "/api/control-plane/delegate",
            json={"task_id": "t-9", "plan_hash": "h-9", "confirm": True},
        )
        assert r.status_code == 200

        from my_crew.runtime.team_task_paths import team_tasks_root

        audit_path = team_tasks_root() / "audit" / "audit.jsonl"
        assert audit_path.exists()
        lines = audit_path.read_text(encoding="utf-8").splitlines()
        assert any('"actor": "control_plane_api"' in ln for ln in lines)


class TestTaskStatus:
    def test_unknown_task_is_404(self, client):
        r = client.get("/api/control-plane/tasks/no-such-task")
        assert r.status_code == 404

    def test_known_task_status_shape(self, client):
        from my_crew.runtime.team_task_paths import team_tasks_db_path
        from my_crew.runtime.team_task_store import TeamTaskStore

        store = TeamTaskStore(team_tasks_db_path())
        store.create_task(task_id="t-status", title="Việc", pic_id="content")
        store.set_plan("t-status", [
            {"step_id": "s1", "title": "bước 1", "assigned_to": "content", "deps": []},
        ], plan_hash="h")
        store.close()

        r = client.get("/api/control-plane/tasks/t-status")
        assert r.status_code == 200
        body = r.json()
        assert body["v"] == 1
        assert body["task_id"] == "t-status"
        assert body["state"]["status"] == "open"
        assert len(body["steps"]) == 1


class TestOverview:
    def test_overview_shape_v1(self, client):
        r = client.get("/api/control-plane/overview")
        assert r.status_code == 200
        body = r.json()
        assert body["v"] == 1
        assert set(body) == {"v", "registry", "health", "queue", "approvals"}


def test_control_plane_routes_are_not_public():
    from my_crew.server.auth import _PUBLIC_PREFIXES

    assert not any(p.startswith("/api/control-plane") for p in _PUBLIC_PREFIXES)
