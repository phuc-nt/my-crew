"""v31 P3 redline: native kanban types `team_task_create`/`team_task_move` — hard
structural categories at every gateway door (both trust modes), store-verified
permissions in the handler (never payload trust), actor identity from closure only.
"""

from __future__ import annotations

import pytest

from my_crew.actions.action_gateway import ActionGateway, HardBlockedError
from my_crew.actions.hard_block import BlockCategory, classify, needs_interrupt
from my_crew.actions.team_task_write import make_team_task_handler
from my_crew.config.config_builders import build_settings_from_dict
from my_crew.runtime.team_task_store import TeamTaskStore


def _settings(tmp_path, trust_mode):
    return build_settings_from_dict({
        "data_dir": tmp_path / "gw", "dry_run": False, "monthly_budget_usd": 50.0,
        "trust_mode": trust_mode,
    })


def _create_action(**over):
    return {"type": "team_task_create", "title": "Viết bài blog", "assignee": "noi-dung",
            **over}


def _move_action(**over):
    return {"type": "team_task_move", "task_id": "abc123def456", "status": "done", **over}


# --- classify: hard categories ---


def test_valid_actions_pass_lop_a():
    assert classify(_create_action()).blocked is False
    assert classify(_move_action()).blocked is False


@pytest.mark.parametrize("action", [
    {"type": "team_task_create"},                                # no title
    _create_action(title=""),                                    # empty title
    _create_action(title="x" * 201),                             # oversized title
    _create_action(assignee="../etc"),                           # id-shape violation
    _create_action(assignee=""),
    {"type": "team_task_move", "status": "done"},                # no task_id
    _move_action(task_id="Robert'); DROP TABLE--"),              # shape violation
    _move_action(status="exploded"),                             # not a store status
    _move_action(status=""),
])
def test_structural_denies_are_hard_categories(action):
    verdict = classify(action)
    assert verdict.blocked
    assert verdict.category == BlockCategory.SECURITY  # holds at execute/approve doors


def test_needs_interrupt_both_types():
    assert needs_interrupt(_create_action()).interrupt is True
    assert needs_interrupt(_move_action()).interrupt is True


# --- gateway doors ---


@pytest.mark.parametrize("trust_mode", ["autonomous", "guarded"])
def test_bad_structure_hard_denied_via_execute(tmp_path, trust_mode):
    gw = ActionGateway(_settings(tmp_path, trust_mode))
    try:
        with pytest.raises(HardBlockedError):
            gw.execute(_move_action(status="exploded"), handler=lambda a: "boom")
        with pytest.raises(HardBlockedError):
            gw.execute_approved(_create_action(title=""), handler=lambda a: "boom")
    finally:
        gw.close()


def test_guarded_queues_autonomous_runs(tmp_path):
    ran = []
    gw = ActionGateway(_settings(tmp_path / "g", "guarded"))
    try:
        assert gw.execute(_create_action(), handler=lambda a: "x").status == "pending_approval"
    finally:
        gw.close()
    gw = ActionGateway(_settings(tmp_path / "a", "autonomous"))
    try:
        result = gw.execute(_create_action(), handler=lambda a: ran.append(a) or "created")
        assert result.status == "executed" and len(ran) == 1
    finally:
        gw.close()


# --- handler: store-verified permissions, closure identity ---


@pytest.fixture
def task_env(tmp_path, monkeypatch):
    """Shared team-task store under a tmp DATA_DIR + a stubbed roster."""
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path / ".data")
    (tmp_path / ".data").mkdir()
    monkeypatch.setattr("my_crew.agent.team_task_roster.is_assignable",
                        lambda agent_id: agent_id in {"noi-dung", "thiet-ke"})
    events = []
    monkeypatch.setattr(
        "my_crew.runtime.office_room_append.append_office_event",
        lambda room_id, *, author, kind, body, also_office=False:
            events.append({"room": room_id, "author": author, "kind": kind, "body": body}),
    )
    return tmp_path / ".data", events


def _store(data_root):
    return TeamTaskStore(data_root / "team_tasks.sqlite3")


def test_create_verifies_roster_and_records(task_env):
    data_root, events = task_env
    summary = make_team_task_handler("truong-phong")(_create_action())
    assert "team task created" in summary
    store = _store(data_root)
    try:
        tasks = store.list_open()
        assert len(tasks) == 1
        task = tasks[0]
        assert task.status == "planning"
        assert task.assigned_by == "truong-phong"  # actor from closure
        assert task.pic_id == "noi-dung"
    finally:
        store.close()
    assert events and events[0]["kind"] == "assignment"


def test_create_rejects_non_roster_assignee(task_env):
    with pytest.raises(PermissionError, match="danh sách nhân sự"):
        make_team_task_handler("truong-phong")(_create_action(assignee="admin"))


def test_move_requires_store_participation(task_env):
    data_root, events = task_env
    store = _store(data_root)
    try:
        store.create_task(task_id="abc123def456", title="Việc A",
                          assigned_by="truong-phong", pic_id="noi-dung")
    finally:
        store.close()
    # A stranger (not PIC/creator/step-assignee) cannot move the card…
    with pytest.raises(PermissionError, match="không phải PIC"):
        make_team_task_handler("thiet-ke")(_move_action(status="done"))
    # …even if the payload smuggles identity fields (closure wins, args ignored).
    with pytest.raises(PermissionError, match="không phải PIC"):
        make_team_task_handler("thiet-ke")(
            _move_action(status="done", actor="noi-dung", agent_id="noi-dung")
        )
    # The PIC can.
    summary = make_team_task_handler("noi-dung")(_move_action(status="done"))
    assert "→ done" in summary
    store = _store(data_root)
    try:
        assert store.get("abc123def456").status == "done"
    finally:
        store.close()
    assert events[-1]["kind"] == "milestone" and events[-1]["body"]["milestone"] == "done"


def test_move_unknown_task_refused(task_env):
    with pytest.raises(PermissionError, match="không có việc"):
        make_team_task_handler("noi-dung")(_move_action(task_id="feedfacecafe"))


def test_move_cannot_open_an_unconfirmed_plan(task_env):
    """confirm_plan is the ONLY planning→dispatchable door: a participant moving a
    drafted-but-unconfirmed task to open/running would let the ticker dispatch a plan
    the CEO never confirmed."""
    data_root, _ = task_env
    store = _store(data_root)
    try:
        store.create_task(task_id="abc123def456", title="Việc nháp",
                          assigned_by="truong-phong", pic_id="noi-dung")
        store.set_draft_plan("abc123def456",
                             [{"step_id": "s1", "title": "bước", "assigned_to": "noi-dung",
                               "deps": []}],
                             plan_hash="draft-hash")
    finally:
        store.close()
    for target in ("open", "running"):
        with pytest.raises(PermissionError, match="xác nhận"):
            make_team_task_handler("noi-dung")(_move_action(status=target))
    store = _store(data_root)
    try:
        assert store.get("abc123def456").status == "planning"  # untouched
    finally:
        store.close()
    # cancelling a draft you participate in is still allowed (no dispatch risk)
    summary = make_team_task_handler("noi-dung")(_move_action(status="cancelled"))
    assert "→ cancelled" in summary


def test_step_assignee_may_move(task_env):
    data_root, _ = task_env
    store = _store(data_root)
    try:
        store.create_task(task_id="abc123def456", title="Việc B",
                          assigned_by="truong-phong", pic_id="noi-dung")
        store.set_plan("abc123def456",
                       [{"step_id": "s1", "title": "bước 1", "assigned_to": "thiet-ke",
                         "deps": []}],
                       plan_hash="h1")
    finally:
        store.close()
    summary = make_team_task_handler("thiet-ke")(_move_action(status="stalled"))
    assert "→ stalled" in summary


# --- catalog + dispatch wiring ---


def test_office_pack_ships_kanban_catalog():
    from my_crew.packs.registry import PackRegistry

    commands = PackRegistry().load("office").commands
    assert {"create_team_task", "move_team_task"} <= set(commands)
    assert commands["create_team_task"]["type"] == "team_task_create"
    assert commands["move_team_task"]["type"] == "team_task_move"


def test_agent_bound_dispatch_routes_team_task(task_env):
    from my_crew.actions.approved_dispatch import make_agent_bound_dispatch

    summary = make_agent_bound_dispatch("truong-phong", config=object())(_create_action())
    assert "team task created" in summary


def test_legacy_dispatch_refuses_team_task():
    from my_crew.actions.approved_dispatch import dispatch_approved_action

    with pytest.raises(RuntimeError, match="agent-bound handler"):
        dispatch_approved_action(_create_action(), config=object())
