"""Delivery-retry sweep (v67 P1): a `done` task whose room milestone never landed is
re-sent from its PERSISTED summary (never re-aggregated), bounded to
`MAX_DELIVERY_ATTEMPTS`, with exactly ONE escalation when the cap is reached."""

from __future__ import annotations

from my_crew.runtime.delivery_retry_sweep import MAX_DELIVERY_ATTEMPTS, run_delivery_retry_sweep
from my_crew.runtime.team_task_store import TeamTaskStore


def _store(tmp_path) -> TeamTaskStore:
    return TeamTaskStore(tmp_path / "team_tasks.sqlite3")


def _undelivered_task(store, task_id="t1", summary="tong ket") -> None:
    store.create_task(task_id=task_id, title=f"viec {task_id}")
    store.set_task_status(task_id, "done")
    store.set_delivery(task_id, status="failed", summary=summary)


def test_retry_success_flips_to_delivered(tmp_path):
    store = _store(tmp_path)
    _undelivered_task(store)
    sent, escalated = [], []

    redelivered = run_delivery_retry_sweep(
        store, lambda task, summary: sent.append((task.id, summary)) or True,
        lambda *a: escalated.append(a),
    )

    assert redelivered == 1
    assert sent == [("t1", "tong ket")]
    task = store.get("t1")
    assert task.delivery_status == "delivered"
    assert task.delivery_attempts == 1
    assert escalated == []
    store.close()


def test_persistent_failure_escalates_exactly_once_at_cap(tmp_path):
    store = _store(tmp_path)
    _undelivered_task(store)
    escalated = []

    # cap sweeps fail, then TWO extra sweeps that must be complete no-ops
    for _ in range(MAX_DELIVERY_ATTEMPTS + 2):
        run_delivery_retry_sweep(
            store, lambda task, summary: False, lambda *a: escalated.append(a[2]),
        )

    task = store.get("t1")
    assert task.delivery_status == "failed"
    assert task.delivery_attempts == MAX_DELIVERY_ATTEMPTS  # no-op sweeps never bump
    assert escalated == ["delivery_failed"]  # exactly once, at the cap transition
    store.close()


def test_raising_deliver_room_still_escalates_at_cap(tmp_path):
    """deliver_room's contract is never-raise, but a violation must count as a failed
    attempt — never skip the cap escalation (the silent-fail class this sweep kills)."""
    store = _store(tmp_path)
    _undelivered_task(store)
    escalated = []

    def _boom(task, summary):
        raise RuntimeError("room store exploded")

    for _ in range(MAX_DELIVERY_ATTEMPTS + 1):
        run_delivery_retry_sweep(store, _boom, lambda *a: escalated.append(a[2]))

    task = store.get("t1")
    assert task.delivery_status == "failed"
    assert task.delivery_attempts == MAX_DELIVERY_ATTEMPTS
    assert escalated == ["delivery_failed"]
    store.close()


def test_delivered_and_not_applicable_tasks_untouched(tmp_path):
    store = _store(tmp_path)
    store.create_task(task_id="ok", title="ok")
    store.set_task_status("ok", "done")
    store.set_delivery("ok", status="delivered", summary="s")
    store.create_task(task_id="manual", title="manual")
    store.set_task_status("manual", "done")  # CEO-interactive: stays not_applicable
    sent = []

    redelivered = run_delivery_retry_sweep(
        store, lambda task, summary: sent.append(task.id) or True, lambda *a: None,
    )

    assert redelivered == 0
    assert sent == []
    assert store.get("ok").delivery_attempts == 0
    assert store.get("manual").delivery_status == "not_applicable"
    store.close()


def test_legacy_row_without_summary_never_resends_and_escalates_at_cap(tmp_path):
    store = _store(tmp_path)
    store.create_task(task_id="t1", title="viec")
    store.set_task_status("t1", "done")
    store.set_delivery("t1", status="pending")  # crash window, no summary persisted
    sent, escalated = [], []

    for _ in range(MAX_DELIVERY_ATTEMPTS + 1):
        run_delivery_retry_sweep(
            store, lambda task, summary: sent.append(task.id) or True,
            lambda *a: escalated.append(a[2]),
        )

    assert sent == []  # nothing to re-send — deliver_room never called
    assert store.get("t1").delivery_status == "failed"
    assert escalated == ["delivery_failed"]
    store.close()
