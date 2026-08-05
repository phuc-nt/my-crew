"""v69 `read_pending_actions` — the reader that carries the action payload.

Separate from `_read_pending` (fleet view, action deliberately omitted). Two
properties matter here and both are security/robustness, not convenience:
read-only so reading a sibling agent never writes schema into its dir, and
raise-on-failure so the digest's echo-suppression is never fooled by an empty
list that actually meant "sqlite broke".
"""

from __future__ import annotations

import sqlite3

import pytest

from my_crew.actions.approval_store import ApprovalStore
from my_crew.runtime.agent_state_reader import read_pending_actions

EMAIL = {"type": "email_send", "to": "ceo@acme.com", "subject": "hi"}


def test_returns_pending_rows_with_their_action(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.db")
    approval_id = store.enqueue(EMAIL, reason="Lớp B", actor="secretary")
    store.close()

    rows = read_pending_actions(tmp_path)
    assert len(rows) == 1
    assert rows[0]["id"] == approval_id
    assert rows[0]["action"]["type"] == "email_send"
    assert rows[0]["actor"] == "secretary"


def test_decided_rows_are_not_pending(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.db")
    approved = store.enqueue(EMAIL, reason="Lớp B")
    still_open = store.enqueue(EMAIL, reason="Lớp B")
    store.set_status(approved, "approved")
    store.close()

    assert [r["id"] for r in read_pending_actions(tmp_path)] == [still_open]


def test_a_missing_db_is_empty_and_stays_missing(tmp_path):
    """Reading an agent that never queued anything must not CREATE its db."""
    assert read_pending_actions(tmp_path) == []
    assert not (tmp_path / "approvals.db").exists()


def test_reading_never_writes_schema_into_a_sibling_dir(tmp_path):
    """`mode=ro`: an empty file must stay empty, not gain an approvals table."""
    db = tmp_path / "approvals.db"
    db.touch()
    with pytest.raises(sqlite3.Error):
        read_pending_actions(tmp_path)
    assert db.stat().st_size == 0


def test_sqlite_failure_raises_instead_of_looking_empty(tmp_path):
    """An empty list on error would read as "nothing pending" to the digest, which
    prunes its reported set from exactly that — and then re-announces everything."""
    (tmp_path / "approvals.db").write_bytes(b"this is not a sqlite database at all")
    with pytest.raises(sqlite3.Error):
        read_pending_actions(tmp_path)


def test_an_unparseable_action_still_yields_the_row(tmp_path):
    """A corrupt payload must not hide the fact that an approval is waiting."""
    db = tmp_path / "approvals.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE approvals (id INTEGER PRIMARY KEY AUTOINCREMENT, action_json TEXT "
        "NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', "
        "rationale TEXT DEFAULT '', created_at TEXT NOT NULL, actor TEXT NOT NULL DEFAULT '')"
    )
    conn.execute(
        "INSERT INTO approvals (action_json, reason, created_at) VALUES (?, ?, ?)",
        ("{not json", "Lớp B", "2026-08-05T10:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    rows = read_pending_actions(tmp_path)
    assert len(rows) == 1
    assert rows[0]["action"] == {}
