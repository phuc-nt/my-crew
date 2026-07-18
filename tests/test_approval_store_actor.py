"""v46: the approval queue records the agent (`actor`) that raised each pending action, and the
`actor` column is added migrate-free so a pre-v46 approvals db keeps working.
"""

from __future__ import annotations

import sqlite3

from my_crew.actions.approval_store import ApprovalStore


def test_enqueue_records_actor_and_round_trips(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.db")
    aid = store.enqueue({"type": "gws_write", "argv": ["x"]}, reason="external", actor="hr")
    got = store.get(aid)
    assert got is not None and got.actor == "hr"
    assert [p.actor for p in store.list_pending()] == ["hr"]


def test_enqueue_actor_defaults_empty(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.db")
    aid = store.enqueue({"type": "gws_write", "argv": ["x"]}, reason="external")  # no actor
    assert store.get(aid).actor == ""


def test_migrate_free_alter_on_pre_v46_db(tmp_path):
    """A pre-v46 approvals db (no `actor` column) must gain it on open, old rows → actor ''."""
    db = tmp_path / "approvals.db"
    # Build a pre-v46 schema (no actor column) + insert a row the old way.
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE approvals ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  action_json TEXT NOT NULL, reason TEXT NOT NULL,"
        "  status TEXT NOT NULL DEFAULT 'pending', rationale TEXT DEFAULT '',"
        "  created_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO approvals (action_json, reason, status, created_at) "
        "VALUES ('{}', 'old', 'pending', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    # Opening via ApprovalStore applies the migrate-free ALTER; the old row reads actor ''.
    store = ApprovalStore(db)
    pend = store.list_pending()
    assert len(pend) == 1 and pend[0].actor == ""
    # a new enqueue on the migrated db carries actor.
    aid = store.enqueue({"type": "x"}, reason="r", actor="tp")
    assert store.get(aid).actor == "tp"
