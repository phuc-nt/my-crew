"""v34 P3: follow-up sweep — SQL detect (stalled / no-progress / waiting-on-CEO),
bounded ladder with cooldown, recovery resets the ladder, no LLM calls.

Load-bearing:
- a stalled task climbs the ladder ONE rung per firing: office event → clarify
  question → Telegram notice, and level 3 repeats (never grows).
- the cooldown gates re-firing; a recovered task resets to level 0.
- waiting-on-CEO steps use their own (shorter) threshold.
- fresh active tasks are never touched.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from my_crew.runtime import follow_up_sweep as fus
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    s = TeamTaskStore(team_tasks_db_path())
    yield s
    s.close()


@pytest.fixture()
def fired(monkeypatch):
    """Capture every ladder rung's transport call instead of doing real I/O."""
    calls = {"event": [], "clarify": [], "notify": []}
    monkeypatch.setattr(
        "my_crew.runtime.office_room_append.append_office_event",
        lambda room, *, author, kind, body, also_office=False: calls["event"].append(body),
    )
    monkeypatch.setattr(
        "my_crew.runtime.office_room_append.room_for_task", lambda tid: tid)
    monkeypatch.setattr(
        "my_crew.runtime.clarify_service.ask_ceo",
        lambda **kw: calls["clarify"].append(kw) or ("note", 1),
    )
    monkeypatch.setattr(
        "my_crew.runtime.operator_notify.notify_operator_best_effort",
        lambda text, **kw: calls["notify"].append(text) or True,
    )
    return calls


def _mk_task(store, task_id, status, *, created_at=None):
    store.create_task(task_id=task_id, title=f"Việc {task_id}", pic_id="")
    store.set_plan(task_id, [{"step_id": "s1", "title": "x", "assigned_to": "a",
                              "deps": []}], "h")
    store._conn.execute("UPDATE team_tasks SET status=? WHERE id=?", (status, task_id))
    if created_at:
        store._conn.execute("UPDATE team_tasks SET created_at=? WHERE id=?",
                            (created_at, task_id))
    store._conn.commit()


_NOW = _dt.datetime(2026, 7, 13, 12, 0, tzinfo=_dt.UTC)


def test_stalled_task_climbs_ladder_one_rung_per_firing(store, fired):
    _mk_task(store, "t1", "stalled")

    assert fus.run_follow_up_sweep(store, now=_NOW) == 1
    assert len(fired["event"]) == 1 and "Nhắc việc" in fired["event"][0]["message"]

    # within cooldown: nothing fires
    soon = _NOW + _dt.timedelta(hours=1)
    assert fus.run_follow_up_sweep(store, now=soon) == 0

    # after cooldown: rung 2 = clarify question with options
    later = _NOW + _dt.timedelta(hours=fus.COOLDOWN_H + 0.1)
    assert fus.run_follow_up_sweep(store, now=later) == 1
    assert fired["clarify"][0]["options"] == ["Đợi thêm", "Huỷ việc này"]
    assert fired["clarify"][0]["agent_id"] == "coordinator"

    # rung 3 = telegram notice; further firings STAY at 3 (repeat, never grow)
    later2 = later + _dt.timedelta(hours=fus.COOLDOWN_H + 0.1)
    assert fus.run_follow_up_sweep(store, now=later2) == 1
    assert len(fired["notify"]) == 1
    later3 = later2 + _dt.timedelta(hours=fus.COOLDOWN_H + 0.1)
    assert fus.run_follow_up_sweep(store, now=later3) == 1
    assert len(fired["notify"]) == 2 and len(fired["clarify"]) == 1


def test_fresh_active_task_is_left_alone(store, fired):
    _mk_task(store, "t2", "running")
    store._conn.execute(
        "UPDATE team_steps SET last_seen=? WHERE task_id='t2'", (_NOW.isoformat(),))
    store._conn.commit()
    assert fus.run_follow_up_sweep(store, now=_NOW) == 0
    assert fired["event"] == [] and fired["clarify"] == [] and fired["notify"] == []


def test_no_progress_task_detected_after_threshold(store, fired):
    old = (_NOW - _dt.timedelta(hours=fus.STUCK_AFTER_H + 1)).isoformat()
    _mk_task(store, "t3", "open", created_at=old)
    # no step was ever touched (spawned_at/last_seen NULL) → created_at is the anchor
    assert fus.run_follow_up_sweep(store, now=_NOW) == 1
    assert "tiến triển" in fired["event"][0]["message"]


def test_waiting_on_ceo_uses_shorter_threshold(store, fired):
    _mk_task(store, "t4", "running")
    stale = (_NOW - _dt.timedelta(hours=fus.WAITING_CEO_AFTER_H + 1)).isoformat()
    store._conn.execute(
        "UPDATE team_steps SET status='waiting_clarify', last_seen=? WHERE task_id='t4'",
        (stale,))
    store._conn.commit()
    assert fus.run_follow_up_sweep(store, now=_NOW) == 1
    assert "chờ CEO" in fired["event"][0]["message"]


def test_recovered_task_resets_ladder(store, fired):
    _mk_task(store, "t5", "stalled")
    fus.run_follow_up_sweep(store, now=_NOW)  # level 1
    # task recovers (CEO fixed it): back to running with fresh activity
    store._conn.execute("UPDATE team_tasks SET status='running' WHERE id='t5'")
    store._conn.execute(
        "UPDATE team_steps SET last_seen=? WHERE task_id='t5'", (_NOW.isoformat(),))
    store._conn.commit()
    later = _NOW + _dt.timedelta(hours=fus.COOLDOWN_H + 0.1)
    assert fus.run_follow_up_sweep(store, now=later) == 0
    level = store._conn.execute(
        "SELECT follow_up_level FROM team_tasks WHERE id='t5'").fetchone()[0]
    assert level == 0  # ladder reset — a NEW stall starts at rung 1 again


def test_failed_rung_does_not_advance_level(store, fired, monkeypatch):
    _mk_task(store, "t6", "stalled")
    monkeypatch.setattr(
        "my_crew.runtime.office_room_append.append_office_event",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("room down")),
    )
    assert fus.run_follow_up_sweep(store, now=_NOW) == 0
    level = store._conn.execute(
        "SELECT follow_up_level FROM team_tasks WHERE id='t6'").fetchone()[0]
    assert level == 0  # nothing recorded — next sweep retries rung 1
