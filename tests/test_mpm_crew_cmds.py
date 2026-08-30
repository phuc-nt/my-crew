"""`mpm crew assign|status|overview` — in-process control-plane CLI (phase 2, plan
`260830-1311-zalo-business-fleet`).

Load-bearing: these call the SAME functions the HTTP router wraps
(`ops_assign_team_task.preview_assign_team_task`/`run_assign_team_task`,
`control_plane_views.build_task_status`/`build_overview`) — tests monkeypatch those
exact functions so drift between the CLI and HTTP surfaces is caught by both test
suites failing together, not just one.
"""

from __future__ import annotations

import my_crew.agent.ops_assign_team_task as assign_mod
from my_crew.entrypoints import mpm
from my_crew.entrypoints import mpm_crew_cmds as crew_cmds


class TestAssign:
    def test_no_brief_is_usage_error(self, capsys):
        rc = crew_cmds.run_crew_control_plane("assign", [])
        assert rc == 2
        assert "usage" in capsys.readouterr().err

    def test_default_two_step_prints_preview_and_confirm_hint(self, monkeypatch, capsys):
        def _fake_preview(slots):
            slots["task_id"] = "t-1"
            slots["plan_hash"] = "h-1"
            return "KẾ HOẠCH..."

        monkeypatch.setattr(assign_mod, "preview_assign_team_task", _fake_preview)
        rc = crew_cmds.run_crew_control_plane("assign", ["viết báo cáo"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "KẾ HOẠCH..." in out
        assert "mpm crew assign --confirm t-1 h-1" in out

    def test_yes_flag_confirms_immediately(self, monkeypatch, capsys):
        def _fake_preview(slots):
            slots["task_id"] = "t-2"
            slots["plan_hash"] = "h-2"
            return "KẾ HOẠCH..."

        monkeypatch.setattr(assign_mod, "preview_assign_team_task", _fake_preview)
        monkeypatch.setattr(
            assign_mod, "run_assign_team_task",
            lambda slots: f"Đã giao việc #{slots['task_id']}",
        )
        rc = crew_cmds.run_crew_control_plane("assign", ["viết báo cáo", "--yes"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Đã giao việc #t-2" in out

    def test_auto_confirmed_preview_skips_second_confirm_call(self, monkeypatch, capsys):
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
        rc = crew_cmds.run_crew_control_plane("assign", ["viết báo cáo", "--yes"])
        assert rc == 0

    def test_confirm_step_dispatches_with_given_hash(self, monkeypatch, capsys):
        seen = {}

        def _fake_run(slots):
            seen.update(slots)
            return "Đã giao việc #t-4"

        monkeypatch.setattr(assign_mod, "run_assign_team_task", _fake_run)
        rc = crew_cmds.run_crew_control_plane(
            "assign", ["--confirm", "t-4", "h-4"]
        )
        assert rc == 0
        assert seen == {"task_id": "t-4", "plan_hash": "h-4"}
        assert "Đã giao việc #t-4" in capsys.readouterr().out

    def test_confirm_stale_hash_prints_error_and_exits_1(self, monkeypatch, capsys):
        def _fake_run(slots):
            raise ValueError("kế hoạch đã thay đổi hoặc hết hạn")

        monkeypatch.setattr(assign_mod, "run_assign_team_task", _fake_run)
        rc = crew_cmds.run_crew_control_plane("assign", ["--confirm", "t-5", "stale"])
        assert rc == 1
        assert "error:" in capsys.readouterr().err

    def test_preview_validation_error_exits_1(self, monkeypatch, capsys):
        def _fake_preview(slots):
            raise ValueError("chưa có đường báo tin")

        monkeypatch.setattr(assign_mod, "preview_assign_team_task", _fake_preview)
        rc = crew_cmds.run_crew_control_plane("assign", ["việc gì đó"])
        assert rc == 1

    def test_room_flag_before_brief_does_not_swallow_the_brief(self, monkeypatch):
        """H5 regression: `--room X "brief"` must not let the room id become the
        brief — the naive `not a.startswith('--')` filter left the VALUE right after
        a flag in the positional list, so `positional[0]` picked up the room id and
        the real brief silently vanished."""
        seen = {}

        def _fake_preview(slots):
            seen.update(slots)
            return "KẾ HOẠCH..."

        monkeypatch.setattr(assign_mod, "preview_assign_team_task", _fake_preview)
        rc = crew_cmds.run_crew_control_plane(
            "assign", ["--room", "room-1", "làm báo cáo tuần"]
        )
        assert rc == 0
        assert seen["brief"] == "làm báo cáo tuần"
        assert seen["room_id"] == "room-1"

    def test_room_flag_after_brief_still_works(self, monkeypatch):
        """The order that happened to work before the fix must keep working."""
        seen = {}

        def _fake_preview(slots):
            seen.update(slots)
            return "KẾ HOẠCH..."

        monkeypatch.setattr(assign_mod, "preview_assign_team_task", _fake_preview)
        rc = crew_cmds.run_crew_control_plane(
            "assign", ["làm báo cáo tuần", "--room", "room-1"]
        )
        assert rc == 0
        assert seen["brief"] == "làm báo cáo tuần"
        assert seen["room_id"] == "room-1"

    def test_confirm_with_room_flag_before_positionals_does_not_swallow_task_id(
        self, monkeypatch
    ):
        """Same bug on the `--confirm` branch: `--confirm --room X t1 h1` must not
        let the room id shift into `task_id`'s slot."""
        seen = {}

        def _fake_run(slots):
            seen.update(slots)
            return "Đã giao việc #t1"

        monkeypatch.setattr(assign_mod, "run_assign_team_task", _fake_run)
        rc = crew_cmds.run_crew_control_plane(
            "assign", ["--confirm", "--room", "room-x", "t1", "h1"]
        )
        assert rc == 0
        assert seen == {"task_id": "t1", "plan_hash": "h1"}


class TestStatus:
    def test_no_task_id_is_usage_error(self, capsys):
        rc = crew_cmds.run_crew_control_plane("status", [])
        assert rc == 2

    def test_unknown_task_exits_1(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "my_crew.server.control_plane_views.build_task_status", lambda tid: None
        )
        rc = crew_cmds.run_crew_control_plane("status", ["no-such-task"])
        assert rc == 1
        assert "không tìm thấy" in capsys.readouterr().err

    def test_known_task_prints_summary(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "my_crew.server.control_plane_views.build_task_status",
            lambda tid: {
                "v": 1, "task_id": tid, "title": "Việc test",
                "state": {"status": "open", "pic_id": "content"},
                "steps": [{"step_id": "s1", "status": "pending", "title": "bước 1",
                           "assigned_to": "content"}],
                "cost": {"total_cost_usd": 0.5},
                "delivery": {"status": "not_applicable", "attempts": 0},
            },
        )
        rc = crew_cmds.run_crew_control_plane("status", ["t-1"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Việc test" in out
        assert "s1" in out
        assert "$0.5000" in out


class TestOverview:
    def test_overview_prints_all_four_blocks(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "my_crew.server.control_plane_views.build_overview",
            lambda: {
                "v": 1,
                "registry": {
                    "agents": [{"agent_id": "content", "enabled": True, "name": "CTV"}],
                },
                "health": {
                    "coordinator_ok": True,
                    "integrations": [
                        {"id": "openrouter", "label": "OpenRouter", "ok": True},
                    ],
                },
                "queue": {"depth": 2, "running": 1, "stalled": 0},
                "approvals": {"pending_total": 1, "pending_by_agent": {"content": 1}},
            },
        )
        rc = crew_cmds.run_crew_control_plane("overview", [])
        assert rc == 0
        out = capsys.readouterr().out
        assert "content" in out
        assert "OpenRouter" in out
        assert "2 đang mở" in out
        assert "content: 1" in out


def test_unknown_subcommand_exits_2(capsys):
    rc = crew_cmds.run_crew_control_plane("bogus", [])
    assert rc == 2
    assert "unknown crew subcommand" in capsys.readouterr().err


class TestMpmDispatchRouting:
    """`mpm crew <action>` at the top-level argparse dispatcher (`mpm.py`) — assign/
    status/overview must route HERE; `init` must still route to the pre-existing
    onboarding command, unmodified (file-ownership: `mpm_onboarding_cmds.py` was not
    touched by this phase)."""

    def test_crew_overview_routes_to_control_plane_module(self, monkeypatch):
        seen = {}

        def _fake(sub, rest):
            seen["call"] = (sub, rest)
            return 0

        monkeypatch.setattr(crew_cmds, "run_crew_control_plane", _fake)
        assert mpm.main(["crew", "overview"]) == 0
        assert seen["call"] == ("overview", [])

    def test_crew_assign_routes_to_control_plane_module(self, monkeypatch):
        seen = {}

        def _fake(sub, rest):
            seen["call"] = (sub, rest)
            return 0

        monkeypatch.setattr(crew_cmds, "run_crew_control_plane", _fake)
        assert mpm.main(["crew", "assign", "việc gì đó"]) == 0
        assert seen["call"] == ("assign", ["việc gì đó"])

    def test_crew_init_still_routes_to_onboarding_module(self, monkeypatch):
        import my_crew.entrypoints.mpm_onboarding_cmds as onb

        seen = {}

        def _fake(sub, rest):
            seen["call"] = (sub, rest)
            return 0

        monkeypatch.setattr(onb, "run_crew", _fake)
        assert mpm.main(["crew", "init"]) == 0
        assert seen["call"] == ("init", [])
