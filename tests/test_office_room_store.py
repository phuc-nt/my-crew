"""Group-chat room store (v12 M29): append/list, room isolation, `also_office`
duplication, PII projection AT WRITE TIME, WAL concurrency smoke.

Load-bearing:
- `append` PROJECTS the body before persisting — a field outside the kind's allowlist
  never lands in the DB (replay of an old row is exactly as safe as the live read).
- `list(room_id, since_seq)` returns only rows after the cursor, in seq order.
- Rooms are isolated: a message appended to room A never appears in room B's `list`.
- `also_office=True` writes a SECOND independent row into the `office` room (own seq),
  not an alias — so each room's cursor stays a simple per-room monotonic count.
- An unknown `kind` is rejected (ValueError), not silently stored empty.
- Two real concurrent writer connections (WAL + busy_timeout) do not raise
  "database is locked".
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from my_crew.runtime.office_room_store import OFFICE_ROOM_ID, OfficeRoomStore, office_room_db_path


def _store(tmp_path) -> OfficeRoomStore:
    return OfficeRoomStore(tmp_path / "office_room.sqlite3")


def test_office_room_db_path_is_data_dir_root(tmp_path):
    assert office_room_db_path(tmp_path) == tmp_path / "office_room.sqlite3"


def test_append_and_list_round_trip(tmp_path):
    store = _store(tmp_path)
    seq = store.append("t1", author="ceo", kind="ceo", body={"text": "chuẩn bị demo"})
    assert seq == 1
    rows = store.list("t1")
    assert len(rows) == 1
    assert rows[0].seq == 1
    assert rows[0].room_id == "t1"
    assert rows[0].author == "ceo"
    assert rows[0].kind == "ceo"
    assert rows[0].body == {"text": "chuẩn bị demo"}
    store.close()


def test_projection_applied_at_write_time_not_read_time(tmp_path):
    """A field outside the `ceo` kind's allowlist must never land in the DB at all —
    not just be hidden on read. Assert directly against the raw sqlite row."""
    store = _store(tmp_path)
    store.append("t1", author="ceo", kind="ceo", body={"text": "ok", "phone": "0900000000"})
    store.close()

    conn = sqlite3.connect(str(tmp_path / "office_room.sqlite3"))
    raw = conn.execute("SELECT body_json FROM messages").fetchone()[0]
    conn.close()
    assert "0900000000" not in raw
    assert "phone" not in raw


def test_since_seq_returns_only_newer_rows(tmp_path):
    store = _store(tmp_path)
    store.append("t1", author="ceo", kind="ceo", body={"text": "one"})
    second_seq = store.append("t1", author="ceo", kind="ceo", body={"text": "two"})
    store.append("t1", author="ceo", kind="ceo", body={"text": "three"})

    rows = store.list("t1", since_seq=second_seq - 1)
    assert [r.body["text"] for r in rows] == ["two", "three"]
    store.close()


def test_rooms_are_isolated(tmp_path):
    store = _store(tmp_path)
    store.append("t1", author="ceo", kind="ceo", body={"text": "for t1"})
    store.append("t2", author="ceo", kind="ceo", body={"text": "for t2"})

    assert [r.body["text"] for r in store.list("t1")] == ["for t1"]
    assert [r.body["text"] for r in store.list("t2")] == ["for t2"]
    store.close()


def test_also_office_writes_a_second_independent_row(tmp_path):
    store = _store(tmp_path)
    store.append(
        "t1", author="coordinator", kind="milestone",
        body={"task_title": "Demo", "milestone": "done", "message": "xong"},
        also_office=True,
    )
    task_rows = store.list("t1")
    office_rows = store.list(OFFICE_ROOM_ID)
    assert len(task_rows) == 1 and len(office_rows) == 1
    # independent seq — not a foreign-key alias of the same row
    assert task_rows[0].seq != office_rows[0].seq
    assert task_rows[0].body == office_rows[0].body
    store.close()


def test_also_office_false_does_not_touch_office_room(tmp_path):
    store = _store(tmp_path)
    store.append("t1", author="ceo", kind="ceo", body={"text": "private to t1"})
    assert store.list(OFFICE_ROOM_ID) == []
    store.close()


def test_office_room_itself_is_not_double_written(tmp_path):
    """Appending directly to the office room with also_office=True must not duplicate
    (the `room_id != OFFICE_ROOM_ID` guard in `append`)."""
    store = _store(tmp_path)
    store.append(
        OFFICE_ROOM_ID, author="coordinator", kind="milestone",
        body={"task_title": "Demo", "milestone": "done", "message": "xong"},
        also_office=True,
    )
    assert len(store.list(OFFICE_ROOM_ID)) == 1
    store.close()


def test_unknown_kind_raises(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.append("t1", author="ceo", kind="not-a-real-kind", body={})
    store.close()


def test_list_rooms_oldest_first_seen(tmp_path):
    store = _store(tmp_path)
    store.append("t2", author="ceo", kind="ceo", body={"text": "second room first message"})
    store.append("t1", author="ceo", kind="ceo", body={"text": "first room second message"})
    assert store.list_rooms() == ["t2", "t1"]
    store.close()


def test_last_seq_tracks_room_max_and_is_zero_when_empty(tmp_path):
    store = _store(tmp_path)
    assert store.last_seq("t1") == 0
    store.append("t1", author="ceo", kind="ceo", body={"text": "a"})
    s2 = store.append("t2", author="ceo", kind="ceo", body={"text": "other room"})
    s3 = store.append("t1", author="ceo", kind="ceo", body={"text": "b"})
    assert store.last_seq("t1") == s3
    assert store.last_seq("t2") == s2  # per-room, not the global max
    store.close()


def test_seq_is_total_order_across_rooms(tmp_path):
    store = _store(tmp_path)
    s1 = store.append("t1", author="ceo", kind="ceo", body={"text": "a"})
    s2 = store.append("t2", author="ceo", kind="ceo", body={"text": "b"})
    s3 = store.append("t1", author="ceo", kind="ceo", body={"text": "c"})
    assert s1 < s2 < s3
    store.close()


def test_wal_concurrent_writers_do_not_lock(tmp_path):
    db_path = tmp_path / "office_room.sqlite3"
    OfficeRoomStore(db_path).close()  # create schema first

    errors: list[Exception] = []

    def _writer(n: int) -> None:
        try:
            store = OfficeRoomStore(db_path)
            for i in range(20):
                store.append("t1", author="ceo", kind="ceo", body={"text": f"{n}-{i}"})
            store.close()
        except Exception as exc:  # noqa: BLE001 — capture for the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=_writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    store = OfficeRoomStore(db_path)
    assert len(store.list("t1")) == 80
    store.close()


# --- source_room_id: room provenance for mirrored events (FE unread per room) ---
#
# The `office` room is a MIRROR of every workroom's notable events, but a projected
# body carries no room linkage for most kinds (`step_status`/`review`/`ceo`/`handoff`
# have no task/room id in their allowlist) — so a client reading only the aggregated
# `office` stream cannot tell which workroom an event came from. `source_room_id` is a
# SCHEMA COLUMN, deliberately not a body field: it stays out of the PII projection
# allowlist entirely (it is the same opaque internal id as `room_id` itself), and every
# kind's projected `body` stays byte-identical to its pre-existing shape.


def test_mirrored_office_row_records_its_source_room(tmp_path):
    store = _store(tmp_path)
    store.append(
        "t1", author="coordinator", kind="step_status",
        body={"task_title": "Demo", "step_title": "B1", "status": "started"},
        also_office=True,
    )
    office_rows = store.list(OFFICE_ROOM_ID)
    assert len(office_rows) == 1
    # the mirror knows where it came from...
    assert office_rows[0].source_room_id == "t1"
    # ...while the body stays exactly what the projection produced (no new body field)
    assert "source_room_id" not in office_rows[0].body


def test_native_row_source_room_is_its_own_room(tmp_path):
    """A non-mirrored row reports its own room, so a consumer never special-cases."""
    store = _store(tmp_path)
    store.append("t1", author="ceo", kind="ceo", body={"text": "hi"})
    assert store.list("t1")[0].source_room_id == "t1"
    store.close()


def test_mirror_and_source_bodies_stay_identical(tmp_path):
    """Provenance rides beside the body, never inside it — the pre-existing contract
    that both rows share one projected body must not regress."""
    store = _store(tmp_path)
    store.append(
        "t1", author="coordinator", kind="milestone",
        body={"task_title": "Demo", "milestone": "done", "message": "xong"},
        also_office=True,
    )
    assert store.list("t1")[0].body == store.list(OFFICE_ROOM_ID)[0].body
    store.close()


def test_source_room_id_survives_reopen_of_pre_existing_db(tmp_path):
    """Adopt path: a store file written before this column exists keeps working, and
    its old rows report their own room_id (no NULL leaking to consumers)."""
    db_path = tmp_path / "office_room.sqlite3"
    # simulate a pre-column DB: create the old schema by hand, insert one row
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE messages ("
        "  seq INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL, ts TEXT NOT NULL,"
        "  author TEXT NOT NULL, kind TEXT NOT NULL, body_json TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO messages (room_id, ts, author, kind, body_json) "
        "VALUES ('t-old', '2026-01-01T00:00:00+00:00', 'ceo', 'ceo', '{\"text\": \"cũ\"}')"
    )
    conn.commit()
    conn.close()

    store = OfficeRoomStore(db_path)
    rows = store.list("t-old")
    assert len(rows) == 1
    assert rows[0].source_room_id == "t-old"  # falls back to the row's own room
    store.close()


def test_last_seq_map_returns_every_room_in_one_query(tmp_path):
    """The conversation list needs an unread count per room. Calling `last_seq` once
    per room is an N+1 against a 127k-row table; one grouped query serves the whole
    list."""
    store = _store(tmp_path)
    store.append("t1", author="ceo", kind="ceo", body={"text": "a"})
    store.append("t2", author="ceo", kind="ceo", body={"text": "b"})
    store.append("t1", author="ceo", kind="ceo", body={"text": "c"})
    assert store.last_seq_map() == {"t1": 3, "t2": 2}


def test_last_seq_map_is_empty_for_empty_store(tmp_path):
    assert _store(tmp_path).last_seq_map() == {}
