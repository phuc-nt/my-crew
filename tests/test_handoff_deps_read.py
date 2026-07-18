"""`team_task_graph._read_deps_handoff`: DEPS-aware handoff read, replacing the old
"seq - 1" shortcut (see that function's docstring for the two failure modes this
fixes: an inserted row between a step and its real producer shifting AUTOINCREMENT
seq, and a parallel branch where "seq - 1" may belong to an unrelated sibling).

Load-bearing:
- a step's deps=[A] but seq-1 belongs to a DIFFERENT step B (inserted between A and
  this step, or a parallel branch) -> reads A's artifact, never B's.
- multiple deps -> concatenates every dep's result_text, in `deps` order.
- no deps -> "" (no read at all, no store hit).
- a dep with no artifact yet (still running) -> contributes nothing, not a crash.
"""

from __future__ import annotations

from my_crew.agent.team_task_artifact import write_step_artifact
from my_crew.agent.team_task_graph import _read_deps_handoff
from my_crew.runtime.team_task_store import TeamTaskStore


def _seed_store(tmp_path, steps: list[dict]) -> None:
    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    store.create_task(task_id="task-1", title="t", original_request="r", assigned_by="ceo")
    store.set_plan("task-1", steps, plan_hash="irrelevant-for-this-test")
    store.close()


def test_no_deps_reads_nothing_and_never_touches_the_store(tmp_path):
    # No store file even exists at tmp_path — if this touched the store it would raise.
    assert _read_deps_handoff(tmp_path, "task-1", ()) == ""


def test_inserted_row_between_step_and_its_real_producer_does_not_misalign_seq_minus_one(tmp_path):
    """seq-1 would point at the wrong step here: A is seq 1, an unrelated inserted row
    (e.g. a review step for a DIFFERENT branch) is seq 2, and THIS step (deps=[A]) is
    seq 3 — "seq - 1" would read the inserted row's artifact, not A's."""
    _seed_store(tmp_path, [
        {"step_id": "a", "title": "draft", "assigned_to": "agent-a", "deps": []},
        {"step_id": "b-unrelated", "title": "unrelated review", "assigned_to": "agent-b",
         "deps": []},
        {"step_id": "c", "title": "final", "assigned_to": "agent-a", "deps": ["a"]},
    ])
    write_step_artifact(
        tmp_path, "task-1", 1, {"status": "done", "result_text": "A's real output"},
    )
    write_step_artifact(
        tmp_path, "task-1", 2, {"status": "done", "result_text": "unrelated content"},
    )

    handoff = _read_deps_handoff(tmp_path, "task-1", ("a",))
    assert handoff == "A's real output"


def test_parallel_branch_seq_minus_one_belongs_to_a_sibling_not_a_dependency(tmp_path):
    """B and C both depend on A and run in parallel (B is seq 2, C is seq 3) — C's
    deps=[A], NOT B, so C must never read B's (possibly still-running/empty) artifact
    just because B happens to be "seq - 1"."""
    _seed_store(tmp_path, [
        {"step_id": "a", "title": "draft", "assigned_to": "agent-a", "deps": []},
        {"step_id": "b", "title": "branch b", "assigned_to": "agent-b", "deps": ["a"]},
        {"step_id": "c", "title": "branch c", "assigned_to": "agent-c", "deps": ["a"]},
    ])
    write_step_artifact(tmp_path, "task-1", 1, {"status": "done", "result_text": "A output"})
    # B (seq 2) has NOT finished yet — no artifact written for it.

    handoff = _read_deps_handoff(tmp_path, "task-1", ("a",))
    assert handoff == "A output"  # never touches B's (seq-1) missing/irrelevant artifact


def test_multiple_deps_concatenate_in_deps_order(tmp_path):
    _seed_store(tmp_path, [
        {"step_id": "a", "title": "draft a", "assigned_to": "agent-a", "deps": []},
        {"step_id": "b", "title": "draft b", "assigned_to": "agent-b", "deps": []},
        {"step_id": "fanin", "title": "combine", "assigned_to": "agent-c", "deps": ["a", "b"]},
    ])
    write_step_artifact(tmp_path, "task-1", 1, {"status": "done", "result_text": "output A"})
    write_step_artifact(tmp_path, "task-1", 2, {"status": "done", "result_text": "output B"})

    handoff = _read_deps_handoff(tmp_path, "task-1", ("a", "b"))
    assert handoff == "output A\n\noutput B"


def test_multiple_deps_order_is_deps_order_not_seq_order(tmp_path):
    """deps lists "b" before "a" — the concatenation must follow THAT order, not the
    steps' insertion/seq order."""
    _seed_store(tmp_path, [
        {"step_id": "a", "title": "draft a", "assigned_to": "agent-a", "deps": []},
        {"step_id": "b", "title": "draft b", "assigned_to": "agent-b", "deps": []},
        {"step_id": "fanin", "title": "combine", "assigned_to": "agent-c", "deps": ["b", "a"]},
    ])
    write_step_artifact(tmp_path, "task-1", 1, {"status": "done", "result_text": "output A"})
    write_step_artifact(tmp_path, "task-1", 2, {"status": "done", "result_text": "output B"})

    handoff = _read_deps_handoff(tmp_path, "task-1", ("b", "a"))
    assert handoff == "output B\n\noutput A"


def test_a_dep_with_no_artifact_yet_contributes_nothing_not_a_crash(tmp_path):
    _seed_store(tmp_path, [
        {"step_id": "a", "title": "draft a", "assigned_to": "agent-a", "deps": []},
        {"step_id": "b", "title": "draft b", "assigned_to": "agent-b", "deps": []},
        {"step_id": "fanin", "title": "combine", "assigned_to": "agent-c", "deps": ["a", "b"]},
    ])
    write_step_artifact(tmp_path, "task-1", 1, {"status": "done", "result_text": "output A"})
    # B (seq 2) never produced an artifact.

    handoff = _read_deps_handoff(tmp_path, "task-1", ("a", "b"))
    assert handoff == "output A"


def test_a_dep_step_id_not_found_in_the_store_is_skipped_not_a_crash(tmp_path):
    _seed_store(tmp_path, [
        {"step_id": "a", "title": "draft a", "assigned_to": "agent-a", "deps": []},
    ])
    write_step_artifact(tmp_path, "task-1", 1, {"status": "done", "result_text": "output A"})

    handoff = _read_deps_handoff(tmp_path, "task-1", ("a", "ghost-step"))
    assert handoff == "output A"
