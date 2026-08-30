"""Unit tests for `control_plane_views` (phase 2 control-plane surface).

Load-bearing:
- `build_task_status` returns None for an unknown task (router maps to 404); shapes
  state/steps/cost/delivery/route for a known one; contract carries `v: 1`.
- `build_overview` degrades EACH of its 4 blocks independently — one block's store
  raising must never blind the other three (phase acceptance criterion).
"""

from __future__ import annotations

import pytest

from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture()
def store(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    s = TeamTaskStore(team_tasks_db_path())
    yield s
    s.close()


def _seed_task(store: TeamTaskStore, task_id: str = "t1") -> None:
    store.create_task(task_id=task_id, title="Việc test", pic_id="content")
    store.set_plan(task_id, [
        {"step_id": "s1", "title": "bước 1", "assigned_to": "content", "deps": []},
    ], plan_hash="hash-1")
    store.set_route(task_id, {"mode": "sprint", "source": "heuristic", "reason": "1 người"})


class TestBuildTaskStatus:
    def test_unknown_task_returns_none(self, store):
        from my_crew.server.control_plane_views import build_task_status

        assert build_task_status("no-such-task") is None

    def test_known_task_shapes_all_blocks(self, store):
        from my_crew.server.control_plane_views import build_task_status

        _seed_task(store)
        result = build_task_status("t1")
        assert result["v"] == 1
        assert result["task_id"] == "t1"
        assert result["state"]["status"] == "open"
        assert result["state"]["pic_id"] == "content"
        assert len(result["steps"]) == 1
        assert result["steps"][0]["step_id"] == "s1"
        assert result["cost"]["total_cost_usd"] == 0.0
        assert result["delivery"]["status"] == "not_applicable"
        assert result["route"]["mode"] == "sprint"

    def test_route_lookup_failure_degrades_to_empty_route(self, store, monkeypatch):
        """A broken route_json (or a store hiccup) must not fail the whole status
        read — only the `route` sub-block empties out."""
        from my_crew.server import control_plane_views

        _seed_task(store)

        def _boom(self, task_id):
            raise RuntimeError("route store exploded")

        monkeypatch.setattr(TeamTaskStore, "get_route", _boom)
        result = control_plane_views.build_task_status("t1")
        assert result is not None
        assert result["route"] == {"mode": "", "source": "", "reason": ""}


class TestBuildOverview:
    def test_all_blocks_present_with_v1(self, store, monkeypatch):
        monkeypatch.setattr("my_crew.runtime.registry.load_registry", lambda *a, **k: [])
        monkeypatch.setattr(
            "my_crew.server.integration_health.integration_checks",
            lambda *a, **k: {"checks": []},
        )
        monkeypatch.setattr(
            "my_crew.server.routes_office_room_chat.get_coordinator_health",
            lambda: {"alive": True},
        )
        from my_crew.server.control_plane_views import build_overview

        result = build_overview()
        assert result["v"] == 1
        assert set(result) == {"v", "registry", "health", "queue", "approvals"}
        assert result["health"]["coordinator_ok"] is True
        assert result["queue"] == {"depth": 0, "running": 0, "stalled": 0}
        assert result["approvals"] == {"pending_total": 0, "pending_by_agent": {}}

    def test_registry_block_failure_does_not_sink_other_blocks(self, store, monkeypatch):
        def _boom():
            raise RuntimeError("registry unreadable")

        monkeypatch.setattr("my_crew.runtime.registry.load_registry", _boom)
        monkeypatch.setattr(
            "my_crew.server.integration_health.integration_checks",
            lambda *a, **k: {"checks": [{"id": "openrouter", "label": "OR", "ok": True}]},
        )
        monkeypatch.setattr(
            "my_crew.server.routes_office_room_chat.get_coordinator_health",
            lambda: {"alive": False},
        )
        from my_crew.server.control_plane_views import build_overview

        result = build_overview()
        assert result["registry"] == {"agents": []}  # degraded, not raised
        assert result["health"]["coordinator_ok"] is False
        assert result["health"]["integrations"][0]["id"] == "openrouter"

    def test_health_block_failure_does_not_sink_other_blocks(self, store, monkeypatch):
        monkeypatch.setattr("my_crew.runtime.registry.load_registry", lambda *a, **k: [])

        def _boom(*a, **k):
            raise RuntimeError("integration probe crashed")

        monkeypatch.setattr("my_crew.server.integration_health.integration_checks", _boom)
        from my_crew.server.control_plane_views import build_overview

        result = build_overview()
        assert result["health"] == {"coordinator_ok": False, "integrations": []}
        assert result["registry"] == {"agents": []}

    def test_queue_block_reflects_dispatchable_and_stalled_counts(self, store, monkeypatch):
        _seed_task(store, "t1")
        store.create_task(task_id="t2", title="Việc 2", pic_id="content")
        store.set_plan("t2", [
            {"step_id": "s1", "title": "b1", "assigned_to": "content", "deps": []},
        ], plan_hash="hash-2")
        store.set_task_status("t2", "stalled")

        monkeypatch.setattr("my_crew.runtime.registry.load_registry", lambda *a, **k: [])
        monkeypatch.setattr(
            "my_crew.server.integration_health.integration_checks",
            lambda *a, **k: {"checks": []},
        )
        monkeypatch.setattr(
            "my_crew.server.routes_office_room_chat.get_coordinator_health",
            lambda: {"alive": True},
        )
        from my_crew.server.control_plane_views import build_overview

        result = build_overview()
        assert result["queue"]["depth"] == 1  # t1 open; t2 stalled excluded from dispatchable
        assert result["queue"]["stalled"] == 1

    def test_approvals_block_aggregates_pending_across_agents(self, store, monkeypatch, tmp_path):
        from my_crew.actions.approval_store import ApprovalStore

        class _Entry:
            def __init__(self, agent_id):
                self.id = agent_id

        agent_dir = tmp_path / "agents" / "content"
        agent_dir.mkdir(parents=True)
        approvals = ApprovalStore(agent_dir / "approvals.db")
        approvals.enqueue({"tool": "x"}, reason="cần duyệt")
        approvals.close()

        monkeypatch.setattr(
            "my_crew.runtime.registry.load_registry", lambda *a, **k: [_Entry("content")]
        )
        monkeypatch.setattr(
            "my_crew.runtime.agent_paths.agent_data_dir",
            lambda agent_id: tmp_path / "agents" / agent_id,
        )
        monkeypatch.setattr(
            "my_crew.server.integration_health.integration_checks",
            lambda *a, **k: {"checks": []},
        )
        monkeypatch.setattr(
            "my_crew.server.routes_office_room_chat.get_coordinator_health",
            lambda: {"alive": True},
        )
        from my_crew.server.control_plane_views import build_overview

        result = build_overview()
        assert result["approvals"] == {"pending_total": 1, "pending_by_agent": {"content": 1}}
