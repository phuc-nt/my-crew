"""The benchmark's own measurements have to be trustworthy.

A harness that quietly reports `n/a` for wall-clock, or that counts a review round as
work, would let a real regression look like a clean run. These tests pin the reading
rules against a store built by hand, so a number in a report can be traced to a row.
"""

from __future__ import annotations

import sqlite3

import pytest

from my_crew.bench.task_metrics import compare, load_task_metric

_TASK_COLS = "id, title, status, created_at, cost_usd_total"
_STEP_COLS = (
    "seq, task_id, step_id, title, assigned_to, deps_json, status, step_type, "
    "cost_usd, spawned_at, last_seen"
)


@pytest.fixture
def store(tmp_path):
    """A minimal team-task store with the columns the reader touches."""
    path = tmp_path / "team_tasks.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE team_tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT, "
        "created_at TEXT, cost_usd_total REAL)"
    )
    conn.execute(
        "CREATE TABLE team_steps (seq INTEGER PRIMARY KEY, task_id TEXT, step_id TEXT, "
        "title TEXT, assigned_to TEXT, deps_json TEXT, status TEXT, step_type TEXT, "
        "cost_usd REAL, spawned_at TEXT, last_seen TEXT)"
    )

    # `seq` is a store-wide primary key, not per-task — steps of two tasks share one
    # counter exactly as they do in the live store.
    next_seq = [1]

    def _add(task_id, created_at, cost, steps):
        conn.execute(
            f"INSERT INTO team_tasks ({_TASK_COLS}) VALUES (?,?,?,?,?)",
            (task_id, "đề bài", "done", created_at, cost),
        )
        for stype, spawned, seen, scost in steps:
            seq = next_seq[0]
            next_seq[0] += 1
            conn.execute(
                f"INSERT INTO team_steps ({_STEP_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (seq, task_id, f"s{seq}", "b", "a", "[]", "done", stype, scost, spawned, seen),
            )
        conn.commit()

    return path, _add


def test_wall_clock_spans_from_the_brief_landing_to_the_last_step(store):
    """The CEO's wait includes the queue gap before the first worker spawned, so the
    span starts at the task's creation — not at the first step."""
    path, add = store
    add(
        "aaa",
        "2026-08-09T10:00:00+00:00",
        0.02,
        [("sprint", "2026-08-09T10:00:30+00:00", "2026-08-09T10:03:19+00:00", 0.015)],
    )
    m = load_task_metric(path, "aaa")
    assert m.wall_clock_seconds == 199.0
    assert m.wall_clock_text == "3m19s"


def test_the_mode_is_read_from_the_step_types_not_guessed(store):
    path, add = store
    add("s1", "2026-08-09T10:00:00+00:00", 0.01,
        [("sprint", "2026-08-09T10:00:00+00:00", "2026-08-09T10:01:00+00:00", 0.01)])
    add("t1", "2026-08-09T10:00:00+00:00", 0.05,
        [("work", "2026-08-09T10:00:00+00:00", "2026-08-09T10:20:00+00:00", 0.05)])
    assert load_task_metric(path, "s1").mode == "sprint"
    assert load_task_metric(path, "t1").mode == "team"


def test_review_and_rework_rounds_are_counted_apart_from_the_work(store):
    """A mode whose output needs two rework rounds is paying a real price. Folding
    them into one step count is exactly how that price would go unnoticed."""
    path, add = store
    add(
        "mix",
        "2026-08-09T10:00:00+00:00",
        0.03,
        [
            ("sprint", "2026-08-09T10:00:00+00:00", "2026-08-09T10:05:00+00:00", 0.02),
            ("review", "2026-08-09T10:05:00+00:00", "2026-08-09T10:05:02+00:00", 0.005),
            ("rework", "2026-08-09T10:05:02+00:00", "2026-08-09T10:07:00+00:00", 0.005),
        ],
    )
    m = load_task_metric(path, "mix")
    assert (m.step_count, m.content_steps, m.review_steps, m.rework_steps) == (3, 2, 1, 1)


def test_a_step_that_never_reported_does_not_erase_the_wall_clock(store):
    """A trailing pending step has no `last_seen`. Reading the final row blindly would
    report `n/a` for a task that plainly finished."""
    path, add = store
    add(
        "tail",
        "2026-08-09T10:00:00+00:00",
        0.01,
        [
            ("sprint", "2026-08-09T10:00:00+00:00", "2026-08-09T10:02:00+00:00", 0.01),
            ("review", None, None, 0.0),
        ],
    )
    m = load_task_metric(path, "tail")
    assert m.wall_clock_text == "2m00s"


def test_the_end_is_the_latest_timestamp_not_the_highest_seq(store):
    """Real shape from team task 7cf21d3bd695: a review row is minted when its work row
    is dispatched, so it holds a HIGHER seq while finishing minutes earlier. Trusting
    row order understated that run's 31 minutes as 21."""
    path, add = store
    add(
        "fanned",
        "2026-08-09T16:19:54+00:00",
        0.07,
        [
            ("work", "2026-08-09T16:36:31+00:00", "2026-08-09T16:41:39+00:00", 0.02),
            ("work", "2026-08-09T16:47:25+00:00", "2026-08-09T16:51:07+00:00", 0.03),
            # minted early, finished first, but sorts last by seq
            ("review", "2026-08-09T16:41:45+00:00", "2026-08-09T16:41:45+00:00", 0.005),
        ],
    )
    m = load_task_metric(path, "fanned")
    assert m.wall_clock_text == "31m13s"


def test_an_unknown_task_reads_as_missing_rather_than_as_zero(store):
    """Zero would quietly become a 'infinitely faster' row in a comparison."""
    path, _ = store
    assert load_task_metric(path, "nope") is None


def test_compare_reports_ratios_between_two_real_runs(store):
    path, add = store
    add("team", "2026-08-09T10:00:00+00:00", 0.07,
        [("work", "2026-08-09T10:00:00+00:00", "2026-08-09T10:36:00+00:00", 0.07)])
    add("spr", "2026-08-09T11:00:00+00:00", 0.017,
        [("sprint", "2026-08-09T11:00:00+00:00", "2026-08-09T11:09:00+00:00", 0.017)])
    out = compare(load_task_metric(path, "team"), load_task_metric(path, "spr"))
    assert out["speedup"] == 4.0
    assert out["cost_ratio"] == pytest.approx(4.12, abs=0.01)


def test_a_missing_measurement_yields_no_ratio_instead_of_a_wrong_one(store):
    path, add = store
    add("a", "2026-08-09T10:00:00+00:00", 0.0, [("work", None, None, 0.0)])
    add("b", "2026-08-09T11:00:00+00:00", 0.01,
        [("sprint", "2026-08-09T11:00:00+00:00", "2026-08-09T11:05:00+00:00", 0.01)])
    out = compare(load_task_metric(path, "a"), load_task_metric(path, "b"))
    assert out["speedup"] is None
    assert out["cost_ratio"] is None
