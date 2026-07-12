"""Telegram milestone mirror (v12 M29): milestone-only filter, persisted cursor, per-day
dedup, batched single DM. Offline (fake gateway/send, real office_room_store + cursor).

Load-bearing:
- Only `kind == "milestone"` rows in the `office` room are pushed — a flood of
  `step_status` events never reaches Telegram (they never even land in the `office`
  room, since only milestone events carry `also_office=True`, but this test also
  exercises the runner's own kind filter directly for defense-in-depth).
- Same (task, milestone, local-date) is pushed at most once per day (dedup); a second
  tick the same day sends nothing new.
- N milestones in one tick become ONE combined Telegram message, not N.
- The cursor persists across calls — a re-run does not re-scan already-mirrored rows.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.runtime.office_room_store import OFFICE_ROOM_ID, OfficeRoomStore, office_room_db_path

NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


class _Tg:
    ops_operator_id = "5248565986"
    chat_ids = ("5248565986",)


class _Cfg:
    telegram = _Tg()
    slack_external_channels = frozenset()


class _Loaded:
    profile_id = "admin"
    domain = "admin"
    config = _Cfg()


class _Settings:
    write_disabled = False
    trust_mode = "guarded"  # pre-v30 behavior; the real gateway reads this in _execute

    def __init__(self, tmp):
        self.data_dir = str(tmp)


def _room(tmp_path) -> OfficeRoomStore:
    return OfficeRoomStore(office_room_db_path(tmp_path))


def _patch_send(monkeypatch, sent: list):
    def _fake_send(text, **kwargs):
        sent.append((text, kwargs["chat_id"]))

        class R:
            status = "executed"
        return R()

    monkeypatch.setattr("src.actions.telegram_write.send_telegram_message", _fake_send)

    class _FakeGateway:
        def __init__(self, *a, **k):
            pass

        def close(self):
            pass

    monkeypatch.setattr("src.actions.action_gateway.ActionGateway", _FakeGateway)


def _run(monkeypatch, tmp_path):
    monkeypatch.setattr("src.runtime.team_task_paths.team_tasks_root", lambda: tmp_path)
    from src.runtime.milestone_mirror_runner import run_milestone_mirror

    return run_milestone_mirror(_Loaded(), _Settings(tmp_path), now=NOW)


def test_milestone_only_filter_ignores_step_status_spam(monkeypatch, tmp_path):
    room = _room(tmp_path)
    # step_status events never land in the office room in the real pipeline (no
    # also_office flag) — seed one directly into "office" to prove the runner's OWN
    # kind filter is defense-in-depth, not the only line of defense.
    room.append(
        "t1", author="agent-a", kind="step_status",
        body={"task_title": "Demo", "step_title": "draft", "status": "started"},
    )
    room.close()
    # manually insert a step_status row straight into the office room (bypassing the
    # store's own room routing) to exercise the runner's kind filter directly
    import sqlite3

    conn = sqlite3.connect(str(office_room_db_path(tmp_path)))
    conn.execute(
        "INSERT INTO messages (room_id, ts, author, kind, body_json) VALUES (?, ?, ?, ?, ?)",
        (OFFICE_ROOM_ID, NOW.isoformat(), "agent-a", "step_status",
         '{"task_title": "Demo", "step_title": "draft", "status": "started"}'),
    )
    conn.commit()
    conn.close()

    sent: list = []
    _patch_send(monkeypatch, sent)
    r = _run(monkeypatch, tmp_path)
    assert sent == []
    assert r["status"] == "no_new_milestones"


def test_milestone_reaches_telegram(monkeypatch, tmp_path):
    room = _room(tmp_path)
    room.append(
        "t1", author="coordinator", kind="milestone",
        body={"task_title": "Demo", "milestone": "done", "message": "xong rồi"},
        also_office=True,
    )
    room.close()

    sent: list = []
    _patch_send(monkeypatch, sent)
    r = _run(monkeypatch, tmp_path)
    assert r["delivered"] is True
    assert len(sent) == 1
    body, chat = sent[0]
    assert chat == "5248565986"
    assert "Demo" in body and "xong rồi" in body


def test_dedup_per_task_milestone_date_no_resend_same_day(monkeypatch, tmp_path):
    room = _room(tmp_path)
    room.append(
        "t1", author="coordinator", kind="milestone",
        body={"task_title": "Demo", "milestone": "done", "message": "xong"},
        also_office=True,
    )
    room.close()

    sent: list = []
    _patch_send(monkeypatch, sent)
    r1 = _run(monkeypatch, tmp_path)
    assert r1["delivered"] is True and len(sent) == 1

    r2 = _run(monkeypatch, tmp_path)
    assert r2["status"] == "no_new_milestones"
    assert len(sent) == 1  # no second send


def test_batched_into_one_combined_message(monkeypatch, tmp_path):
    room = _room(tmp_path)
    room.append(
        "t1", author="coordinator", kind="milestone",
        body={"task_title": "Demo A", "milestone": "received", "message": "nhận việc A"},
        also_office=True,
    )
    room.append(
        "t2", author="coordinator", kind="milestone",
        body={"task_title": "Demo B", "milestone": "done", "message": "xong B"},
        also_office=True,
    )
    room.close()

    sent: list = []
    _patch_send(monkeypatch, sent)
    r = _run(monkeypatch, tmp_path)
    assert r["delivered"] is True
    assert len(sent) == 1  # ONE combined message for 2 milestones
    body, _chat = sent[0]
    assert "Demo A" in body and "Demo B" in body


def test_cursor_persists_across_calls_no_rescan(monkeypatch, tmp_path):
    room = _room(tmp_path)
    room.append(
        "t1", author="coordinator", kind="milestone",
        body={"task_title": "Demo", "milestone": "received", "message": "nhận việc"},
        also_office=True,
    )
    room.close()

    sent: list = []
    _patch_send(monkeypatch, sent)
    _run(monkeypatch, tmp_path)  # first tick consumes it
    assert len(sent) == 1

    # second tick with NOTHING new appended must report zero checked (cursor advanced,
    # not re-reading the already-seen row)
    r2 = _run(monkeypatch, tmp_path)
    assert r2["checked"] == 0


def test_no_operator_is_noop(monkeypatch, tmp_path):
    class _NoTg:
        telegram = None
        slack_external_channels = frozenset()

    class _L:
        profile_id = "x"
        domain = "admin"
        config = _NoTg()

    monkeypatch.setattr("src.runtime.team_task_paths.team_tasks_root", lambda: tmp_path)
    from src.runtime.milestone_mirror_runner import run_milestone_mirror

    r = run_milestone_mirror(_L(), _Settings(tmp_path), now=NOW)
    assert r["status"] == "no_operator" and r["delivered"] is False


def test_writes_disabled_pushes_nothing(monkeypatch, tmp_path):
    room = _room(tmp_path)
    room.append(
        "t1", author="coordinator", kind="milestone",
        body={"task_title": "Demo", "milestone": "done", "message": "xong"},
        also_office=True,
    )
    room.close()

    monkeypatch.setattr("src.runtime.team_task_paths.team_tasks_root", lambda: tmp_path)
    from src.runtime.milestone_mirror_runner import run_milestone_mirror

    s = _Settings(tmp_path)
    s.write_disabled = True
    r = run_milestone_mirror(_Loaded(), s, now=NOW)
    assert r["status"] == "writes_disabled" and r["delivered"] is False


# --- ordering: cursor must not advance past a tick that never sent -----------------


def test_write_disabled_tick_does_not_advance_the_cursor_so_it_retries_next_run(
    monkeypatch, tmp_path,
):
    """A `write_disabled` tick must not lose the milestone: the cursor stays put so the
    SAME row is re-read (and re-attempted) the next time writes are enabled — advancing
    it here would silently drop the milestone forever."""
    room = _room(tmp_path)
    room.append(
        "t1", author="coordinator", kind="milestone",
        body={"task_title": "Demo", "milestone": "done", "message": "xong"},
        also_office=True,
    )
    room.close()

    monkeypatch.setattr("src.runtime.team_task_paths.team_tasks_root", lambda: tmp_path)
    from src.runtime.milestone_mirror_runner import run_milestone_mirror

    s = _Settings(tmp_path)
    s.write_disabled = True
    r1 = run_milestone_mirror(_Loaded(), s, now=NOW)
    assert r1["status"] == "writes_disabled"

    sent: list = []
    _patch_send(monkeypatch, sent)
    s.write_disabled = False
    r2 = run_milestone_mirror(_Loaded(), s, now=NOW)
    assert r2["delivered"] is True and len(sent) == 1


def test_dedup_is_keyed_by_task_id_not_task_title_two_tasks_same_title_both_deliver(
    monkeypatch, tmp_path,
):
    """Two DISTINCT tasks that happen to share the same free-text title (a CEO brief
    reused, or a decompose-LLM producing the same wording twice) must both reach
    Telegram — a title-keyed dedup would collide them into a single claim and silently
    drop the second task's milestone."""
    room = _room(tmp_path)
    room.append(
        "task-a", author="coordinator", kind="milestone",
        body={"task_id": "task-a", "task_title": "Demo", "milestone": "done", "message": "xong A"},
        also_office=True,
    )
    room.append(
        "task-b", author="coordinator", kind="milestone",
        body={"task_id": "task-b", "task_title": "Demo", "milestone": "done", "message": "xong B"},
        also_office=True,
    )
    room.close()

    sent: list = []
    _patch_send(monkeypatch, sent)
    r = _run(monkeypatch, tmp_path)
    assert r["delivered"] is True
    body, _chat = sent[0]
    assert "xong A" in body and "xong B" in body
