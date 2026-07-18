"""v36 P1: storage retention GC + schema_meta versioning + integrity audit.

GC removes over-age telemetry/event/settled-clarify/dedup rows; it must never touch
in-flight data (pending clarify) or business history (team_tasks/team_steps). schema_meta
stamps a version and adopts an old DB. The integrity audit is read-only + daily-gated.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from my_crew.actions.dedup_store import DedupStore
from my_crew.runtime.capture_store import CaptureStore
from my_crew.runtime.clarify_store import ClarifyStore
from my_crew.runtime.office_room_store import OfficeRoomStore
from my_crew.runtime.store_schema_meta import (
    SCHEMA_VERSION,
    ensure_schema_meta,
    read_schema_version,
)

_NOW = datetime(2026, 7, 13, 3, 0, 0)


def _iso(days_ago: int) -> str:
    return (_NOW - timedelta(days=days_ago)).isoformat()


# ---- captures ----------------------------------------------------------------

def _record_capture(store, attempt_id, ts):
    # `record()` stamps ts=now internally; to age a row we insert with an explicit ts.
    store._conn.execute(
        "INSERT INTO captures (attempt_id, task_id, step_id, status, ts) VALUES (?,?,?,?,?)",
        (attempt_id, "t1", "s1", "done", ts),
    )
    store._conn.commit()


def test_captures_gc_removes_over_age_keeps_recent(tmp_path):
    store = CaptureStore(tmp_path / "captures.sqlite3")
    _record_capture(store, "old", _iso(200))
    _record_capture(store, "fresh", _iso(10))
    removed = store.delete_older_than(_iso(180))
    assert removed == 1
    rows = {r[0] for r in store._conn.execute("SELECT attempt_id FROM captures")}
    assert rows == {"fresh"}
    store.close()


# ---- office_room -------------------------------------------------------------

def test_office_gc_removes_old_events(tmp_path):
    store = OfficeRoomStore(tmp_path / "office_room.sqlite3")
    store._conn.execute(
        "INSERT INTO messages (room_id, ts, author, kind, body_json) VALUES (?,?,?,?,?)",
        ("r1", _iso(100), "a", "msg", "{}"),
    )
    store._conn.execute(
        "INSERT INTO messages (room_id, ts, author, kind, body_json) VALUES (?,?,?,?,?)",
        ("r1", _iso(5), "a", "msg", "{}"),
    )
    store._conn.commit()
    removed = store.delete_older_than(_iso(90))
    assert removed == 1
    remaining = store.list("r1")
    assert len(remaining) == 1  # advancing-cursor read still works after GC
    store.close()


# ---- clarify -----------------------------------------------------------------

def _insert_clarify(store, status, asked, answered, expires):
    store._conn.execute(
        "INSERT INTO clarifications "
        "(agent_id, question, status, asked_at, answered_at, expires_at) "
        "VALUES (?,?,?,?,?,?)",
        ("a", "q?", status, asked, answered, expires),
    )
    store._conn.commit()


def test_clarify_gc_settled_only_never_pending(tmp_path):
    store = ClarifyStore(tmp_path / "clarify.sqlite3")
    _insert_clarify(store, "answered", _iso(100), _iso(100), _iso(90))
    _insert_clarify(store, "expired", _iso(100), None, _iso(100))
    _insert_clarify(store, "pending", _iso(100), None, _iso(-1))  # OLD but still open
    _insert_clarify(store, "answered", _iso(5), _iso(5), _iso(1))  # recent
    removed = store.delete_older_than(_iso(90))
    assert removed == 2  # the two old settled rows
    left = {r[0] for r in store._conn.execute("SELECT status FROM clarifications")}
    assert left == {"pending", "answered"}  # pending survived despite age
    store.close()


# ---- dedup -------------------------------------------------------------------

def test_dedup_gc(tmp_path):
    store = DedupStore(tmp_path / "dedup.db")
    store._conn.execute("INSERT INTO seen_keys (key, created_at) VALUES ('old', ?)", (_iso(30),))
    store._conn.execute("INSERT INTO seen_keys (key, created_at) VALUES ('new', ?)", (_iso(1),))
    store._conn.commit()
    assert store.delete_older_than(_iso(7)) == 1
    assert store.seen("new") and not store.seen("old")
    store.close()


# ---- schema_meta -------------------------------------------------------------

def test_schema_meta_stamped_on_new_store(tmp_path):
    store = CaptureStore(tmp_path / "captures.sqlite3")
    assert read_schema_version(store._conn) == SCHEMA_VERSION
    store.close()


def test_schema_meta_adopts_existing_db(tmp_path):
    # A DB created WITHOUT schema_meta (pre-v36) adopts the current version on ensure.
    db = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()
    assert read_schema_version(conn) is None
    assert ensure_schema_meta(conn) == SCHEMA_VERSION
    assert read_schema_version(conn) == SCHEMA_VERSION
    # Idempotent: a second call keeps the recorded version.
    assert ensure_schema_meta(conn, version=99) == SCHEMA_VERSION
    conn.close()


# ---- orchestrator ------------------------------------------------------------

def test_retention_sweep_survives_a_broken_store(monkeypatch, tmp_path):
    from my_crew.runtime import storage_hygiene

    # captures opener raises; sweep must still return and record the others.
    def _boom():
        raise sqlite3.OperationalError("locked")

    # The store constructors raise before any path is used, so only the openers + the
    # (empty) registry need patching — the sweep must still return the survivors.
    monkeypatch.setattr("my_crew.runtime.capture_store.CaptureStore", lambda p: _boom())
    monkeypatch.setattr("my_crew.runtime.office_room_store.OfficeRoomStore", lambda p: _boom())
    monkeypatch.setattr("my_crew.runtime.clarify_store.ClarifyStore", lambda p: _boom())
    monkeypatch.setattr("my_crew.runtime.registry.load_registry", lambda: ())
    out = storage_hygiene.run_retention_sweep(now=_NOW)
    # Broken stores are simply absent from the result; dedup ran (empty registry → 0).
    assert out == {"dedup": 0}


def test_integrity_audit_flags_orphans_daily_gated(monkeypatch, tmp_path):
    from my_crew.runtime import storage_hygiene

    db = tmp_path / "team_tasks.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE team_tasks (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE team_steps (task_id TEXT)")
    conn.execute("INSERT INTO team_tasks (id) VALUES ('t1')")
    conn.execute("INSERT INTO team_steps (task_id) VALUES ('t1')")
    conn.execute("INSERT INTO team_steps (task_id) VALUES ('ghost')")  # orphan
    conn.commit()
    conn.close()

    monkeypatch.setattr("my_crew.runtime.team_task_paths.team_tasks_db_path", lambda: db)
    monkeypatch.setattr("my_crew.runtime.team_task_paths.team_tasks_root", lambda: tmp_path)

    lines = storage_hygiene.run_integrity_audit(now=_NOW)
    assert any("missing task" in ln for ln in lines)
    # Daily gate: an immediate second call is suppressed.
    assert storage_hygiene.run_integrity_audit(now=_NOW + timedelta(minutes=1)) == []
    # Next day: runs again.
    assert storage_hygiene.run_integrity_audit(now=_NOW + timedelta(days=1, minutes=1))
