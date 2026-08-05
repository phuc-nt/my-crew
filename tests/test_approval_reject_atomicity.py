"""v69 prerequisites for a third approval surface: reject is compare-and-set, and
the store survives concurrent writers.

Three surfaces (CLI, web, ops-chat) now decide the same queue. A blind reject could
land on a row another surface already approved and EXECUTED, leaving the store
claiming "rejected" for an action that really ran — and, worse, teaching a standing
deny rule from that phantom decision.
"""

from __future__ import annotations

import sqlite3

from my_crew.actions.action_gateway import ActionGateway
from my_crew.actions.approval_store import ApprovalStore
from my_crew.audit.audit_log import AuditLog

EMAIL = {"type": "email_send", "to": "ceo@acme.com", "subject": "hi", "body": "chi tiết"}


def _gw(settings_factory, tmp_path, name="audit"):
    return ActionGateway(
        settings=settings_factory(dry_run=False),
        audit_log=AuditLog(tmp_path / f"{name}.jsonl"),
        notify_enqueued=lambda *a: None,
    )


def test_rejecting_a_pending_row_wins_and_reports_it(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path)
    queued = gw.execute(EMAIL, handler=lambda a: "SENT")
    assert gw.reject(queued.approval_id) is True
    assert gw._approvals.get(queued.approval_id).status == "rejected"


def test_rejecting_an_already_approved_row_loses_the_race(settings_factory, tmp_path):
    """The row ran. A reject arriving afterwards must not overwrite that fact."""
    gw = _gw(settings_factory, tmp_path)
    queued = gw.execute(EMAIL, handler=lambda a: "SENT")
    gw.approve(queued.approval_id, handler=lambda a: "SENT")

    assert gw.reject(queued.approval_id) is False
    assert gw._approvals.get(queued.approval_id).status == "approved"


def test_a_second_reject_is_a_no_op(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path)
    queued = gw.execute(EMAIL, handler=lambda a: "SENT")
    assert gw.reject(queued.approval_id) is True
    assert gw.reject(queued.approval_id) is False


def test_rejecting_an_unknown_id_is_false_not_a_crash(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path)
    assert gw.reject(9999) is False


def test_a_lost_race_audits_nothing(settings_factory, tmp_path):
    """A decision that was not ours must leave no 'reject' verdict in our audit trail."""
    gw = _gw(settings_factory, tmp_path)
    queued = gw.execute(EMAIL, handler=lambda a: "SENT")
    gw.approve(queued.approval_id, handler=lambda a: "SENT")
    before = (tmp_path / "audit.jsonl").read_text()

    gw.reject(queued.approval_id)
    assert (tmp_path / "audit.jsonl").read_text() == before


# --- store durability under concurrent writers ---


def test_store_opens_in_wal_mode(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.db")
    try:
        mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        store.close()


def test_a_second_process_can_write_while_the_first_holds_the_file(tmp_path):
    """Two surfaces on one queue is the normal case now, not an edge case."""
    db = tmp_path / "approvals.db"
    first = ApprovalStore(db)
    second = ApprovalStore(db)
    try:
        a = first.enqueue(EMAIL, reason="Lớp B", actor="secretary")
        b = second.enqueue(EMAIL, reason="Lớp B", actor="coordinator")
        assert a != b
        # Each connection sees the other's row.
        assert {p.id for p in first.list_pending()} == {a, b}
        assert {p.id for p in second.list_pending()} == {a, b}
    finally:
        first.close()
        second.close()


def test_only_one_connection_can_win_the_same_transition(tmp_path):
    """Compare-and-set holds ACROSS connections, which is where it actually matters."""
    db = tmp_path / "approvals.db"
    first = ApprovalStore(db)
    second = ApprovalStore(db)
    try:
        approval_id = first.enqueue(EMAIL, reason="Lớp B")
        assert first.transition_if_pending(approval_id, "approved") is True
        assert second.transition_if_pending(approval_id, "rejected") is False
        assert second.get(approval_id).status == "approved"
    finally:
        first.close()
        second.close()


def test_busy_timeout_is_set_wide_enough_to_wait_out_a_writer(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.db")
    try:
        assert store._conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 30000
    finally:
        store.close()


def test_an_existing_rollback_journal_db_is_upgraded_in_place(tmp_path):
    """Real users have approvals.db files created before WAL. Opening must migrate them,
    not fail and not lose the rows already queued."""
    db = tmp_path / "approvals.db"
    legacy = sqlite3.connect(str(db))
    legacy.execute(
        "CREATE TABLE approvals (id INTEGER PRIMARY KEY AUTOINCREMENT, action_json TEXT "
        "NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', "
        "rationale TEXT DEFAULT '', created_at TEXT NOT NULL)"
    )
    legacy.execute(
        "INSERT INTO approvals (action_json, reason, created_at) VALUES ('{}', 'cũ', 'x')"
    )
    legacy.commit()
    legacy.close()

    store = ApprovalStore(db)
    try:
        assert store._conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert len(store.list_pending()) == 1
    finally:
        store.close()
