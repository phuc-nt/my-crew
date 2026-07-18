"""`confirm_amendment` vs the ticker's `reserve_step`, forced interleave (v13 M34):
SQLite's single-writer serialization (`BEGIN IMMEDIATE`) is the actual concurrency
primitive here — two REAL connections to the same on-disk store, deterministically
interleaved via a background thread blocked on SQLite's own busy-lock (no sleeps, no
timing guesses): whichever transaction acquires the write lock first completes
atomically before the other can even start writing, so the outcome is always either
"confirm won, swap applied, the racing reserve blocked until commit and can act on the
POST-swap DAG" or "reserve won first, confirm's re-validate/swap sees the step already
running and rejects" — never a torn state (no orphaned running step outside team_steps,
no duplicate step row, no partial swap).
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from my_crew.agent.task_decomposition import decomposition_content_hash
from my_crew.runtime.team_task_amend import full_dag_plan_hash
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


def _content_hash(steps: list[dict]) -> str:
    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(
            step_id=s["step_id"], title=s["title"], assigned_to=s["assigned_to"],
            deps=tuple(s.get("deps", ())),
        )
        for s in steps
    ]))


def _plan(store: TeamTaskStore, task_id="t1") -> None:
    steps = [
        {"step_id": "s1", "title": "A", "assigned_to": "agent-a", "deps": []},
    ]
    store.create_task(task_id=task_id, title="demo task", original_request="lam demo")
    store.set_plan(task_id, steps, plan_hash=_content_hash(steps))


def _draft_replacing_pending(store: TeamTaskStore, task_id: str, new_step_id: str) -> str:
    task = store.get(task_id)
    base_hash = full_dag_plan_hash(task.steps)
    old_pending_ids = [s.step_id for s in task.steps if s.status == "pending"]
    new_pending = [{"step_id": new_step_id, "title": new_step_id, "assigned_to": "agent-a",
                    "deps": []}]
    new_hash = _content_hash(new_pending)  # s1 was the only step, all pending -> fully replaced
    return store.set_amendment_draft(
        task_id, base_plan_hash=base_hash, new_plan_hash=new_hash,
        new_pending_steps=new_pending, old_pending_step_ids=old_pending_ids,
    )


def test_reserve_blocked_until_confirm_transaction_finishes_then_sees_post_swap_dag(
    tmp_path, monkeypatch,
):
    """Confirm's `BEGIN IMMEDIATE` acquires the write lock BEFORE the racing reserve
    even attempts its own write — the reserve call (on a second real connection) blocks
    on SQLite's busy-lock (via `busy_timeout`) until confirm's REAL transaction commits,
    then runs against the ALREADY-SWAPPED DAG: `s1` is gone (swapped away by the
    confirmed amendment), so reserving it fails loud rather than silently reviving a
    step the amendment removed.

    The forced interleave point is genuine, not simulated: `swap_pending_steps` (called
    from INSIDE `confirm_amendment`'s held `BEGIN IMMEDIATE`) is wrapped to signal
    "confirm's write lock is now held" and block until the racing thread has started
    its own (SQLite-blocked) reserve attempt, before letting confirm's real swap +
    commit proceed — no sleeps, synchronized purely via `threading.Event`s.
    """
    db_path = tmp_path / "team_tasks.sqlite3"
    store_main = TeamTaskStore(db_path)
    _plan(store_main, "t1")
    amendment_id = _draft_replacing_pending(store_main, "t1", "s2")

    store_reserve = TeamTaskStore(db_path)
    confirm_holds_lock = threading.Event()
    reserve_attempted = threading.Event()

    import my_crew.runtime.team_task_steps as steps_mod

    real_swap = steps_mod.swap_pending_steps

    def _swap_then_wait_for_racing_reserve(*args, **kwargs):
        confirm_holds_lock.set()
        reserve_attempted.wait(timeout=5)
        return real_swap(*args, **kwargs)

    # `confirm_amendment` does `from my_crew.runtime import team_task_steps as _steps`
    # LOCALLY inside its own function body (not a module-level import on
    # `team_task_amend`), so the patch target is the real `team_task_steps` module
    # attribute itself — the local import binds to this same module object at call time.
    monkeypatch.setattr(steps_mod, "swap_pending_steps", _swap_then_wait_for_racing_reserve)

    reserve_outcome: dict[str, object] = {}

    def _racing_reserve() -> None:
        confirm_holds_lock.wait(timeout=5)  # wait until confirm's BEGIN IMMEDIATE is live
        reserve_attempted.set()  # signal BEFORE the (SQLite-blocking) call, not after
        try:
            attempt_id = store_reserve.reserve_step("t1", "s1")
            reserve_outcome["ok"] = True
            reserve_outcome["attempt_id"] = attempt_id
        except ValueError as exc:
            reserve_outcome["ok"] = False
            reserve_outcome["error"] = str(exc)

    thread = threading.Thread(target=_racing_reserve)
    thread.start()

    result = store_main.confirm_amendment("t1", amendment_id)
    thread.join(timeout=5)
    assert not thread.is_alive()

    assert result.ok is True  # confirm holds the write lock first -> wins outright
    # The racing reserve was BLOCKED by SQLite's own busy-lock while confirm's
    # transaction was open, then ran against the POST-swap DAG once confirm committed —
    # s1 no longer exists, so reserving it fails loud rather than reviving a removed step.
    assert reserve_outcome["ok"] is False
    assert "unknown team step" in reserve_outcome["error"]

    task = store_main.get("t1")
    assert {s.step_id for s in task.steps} == {"s2"}  # exactly one step, no duplicate, no orphan

    store_reserve.close()
    store_main.close()


def test_reserve_wins_the_race_confirm_then_rejects_and_swap_never_applies(tmp_path):
    """The opposite interleave: the ticker's `reserve_step` commits FIRST (s1 goes
    pending -> running before confirm's transaction even starts) — confirm's swap must
    detect this via `old_pending_step_ids` and reject, leaving s1 running (never
    clobbered) and NOT inserting the amendment's replacement step at all (no orphan,
    no duplicate, no partial DAG)."""
    db_path = tmp_path / "team_tasks.sqlite3"
    store_main = TeamTaskStore(db_path)
    _plan(store_main, "t1")
    amendment_id = _draft_replacing_pending(store_main, "t1", "s2")

    store_reserve = TeamTaskStore(db_path)
    attempt_id = store_reserve.reserve_step("t1", "s1")  # wins the race outright, commits first

    result = store_main.confirm_amendment("t1", amendment_id)
    assert result.ok is False
    assert result.reason == "pending_step_just_reserved"
    assert result.skipped_step_ids == ("s1",)

    task = store_main.get("t1")
    by_id = {s.step_id: s for s in task.steps}
    assert set(by_id) == {"s1"}  # no s2 inserted — the rejected swap applied nothing
    assert by_id["s1"].status == "running"
    assert by_id["s1"].attempt_id == attempt_id  # untouched, still the reserving worker's lease

    draft = store_main.get_amendment_draft(amendment_id)
    assert draft.status == "draft"  # re-previewable, not silently lost

    store_reserve.close()
    store_main.close()
