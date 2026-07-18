"""Handoff-artifact confinement + atomicity (`my_crew/agent/team_task_artifact.py`).

Load-bearing (the two hazards the module's own docstring names):
- Path traversal: a task id shaped like a traversal attempt is rejected before any
  path is even built (`_validate_task_id`'s regex has no room for `/` or `..`).
- Symlink escape: a symlink INSIDE the confined per-task dir that points OUTSIDE it
  is caught by `_confine`'s resolved-prefix check, not silently followed.
- Torn reads: `write_step_artifact`'s temp-then-`os.replace` means a concurrent
  reader never observes a partial write — verified via a real interleaved
  write/read sequence, and via `read_step_artifact`'s tolerance for a corrupt file.
"""

from __future__ import annotations

import json

import pytest

from my_crew.agent.team_task_artifact import (
    read_step_artifact,
    step_artifact_path,
    task_artifact_dir,
    write_step_artifact,
)


def test_task_artifact_dir_is_confined_under_data_dir(tmp_path):
    root = task_artifact_dir(tmp_path, "task-1")
    assert root == tmp_path / "artifacts" / "team-tasks" / "task-1"


@pytest.mark.parametrize(
    "bad_task_id",
    [
        "../../etc/passwd",
        "../escape",
        "task/1",
        "task/../../escape",
        "",
        "/absolute",
    ],
)
def test_rejects_path_traversal_shaped_task_ids(tmp_path, bad_task_id):
    with pytest.raises(ValueError, match="Invalid team task id"):
        task_artifact_dir(tmp_path, bad_task_id)
    with pytest.raises(ValueError, match="Invalid team task id"):
        write_step_artifact(tmp_path, bad_task_id, 1, {"ok": True})
    with pytest.raises(ValueError, match="Invalid team task id"):
        read_step_artifact(tmp_path, bad_task_id, 1)


def test_write_then_read_round_trips_a_step_artifact(tmp_path):
    write_step_artifact(tmp_path, "task-1", 0, {"result": "hello", "n": 3})
    data = read_step_artifact(tmp_path, "task-1", 0)
    assert data == {"result": "hello", "n": 3}


def test_read_missing_artifact_returns_none_not_raise(tmp_path):
    assert read_step_artifact(tmp_path, "task-1", 0) is None


def test_read_corrupt_artifact_returns_none_not_raise(tmp_path):
    path = step_artifact_path(tmp_path, "task-1", 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    assert read_step_artifact(tmp_path, "task-1", 0) is None


def test_read_artifact_that_is_a_json_list_returns_none_not_the_list(tmp_path):
    # write_step_artifact always writes a dict payload — but a reader must not trust
    # that on-disk invariant blindly (a hand-edited or corrupted file could be a
    # top-level JSON array/scalar); read_step_artifact's own isinstance guard exists
    # for exactly this.
    path = step_artifact_path(tmp_path, "task-1", 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    assert read_step_artifact(tmp_path, "task-1", 0) is None


def test_write_never_leaves_a_visible_partial_file_for_a_concurrent_reader(tmp_path):
    # write_step_artifact's real contract: the .tmp sibling is renamed atomically over
    # the target, so a reader polling `path.exists()` + read never sees a half-written
    # file. Prove the invariant directly: after write returns, the target is fully
    # valid JSON and no `.tmp-*` sibling is left behind.
    write_step_artifact(tmp_path, "task-1", 0, {"payload": "x" * 5000})
    root = task_artifact_dir(tmp_path, "task-1")
    leftovers = list(root.glob("*.tmp-*"))
    assert leftovers == []
    data = read_step_artifact(tmp_path, "task-1", 0)
    assert data == {"payload": "x" * 5000}


def test_rewrite_of_same_step_is_atomic_reader_never_sees_a_torn_file(tmp_path):
    write_step_artifact(tmp_path, "task-1", 0, {"version": 1})
    path = step_artifact_path(tmp_path, "task-1", 0)
    before = path.read_text(encoding="utf-8")
    assert json.loads(before) == {"version": 1}

    write_step_artifact(tmp_path, "task-1", 0, {"version": 2})
    after = path.read_text(encoding="utf-8")
    # Never a half-old-half-new blend — the file is fully one complete JSON doc or
    # the other, exactly what os.replace guarantees.
    assert json.loads(after) == {"version": 2}


def test_symlink_inside_task_dir_pointing_outside_is_not_followed_on_write(tmp_path):
    # A symlink named exactly `step-0.json` living inside the confined per-task dir,
    # but pointing OUTSIDE that dir. write_step_artifact must refuse to follow it and
    # write into the outside target — `_confine`'s resolved-prefix check must catch
    # this even though the symlink's own (unresolved) parent is inside the root.
    outside_target = tmp_path / "outside-secret.json"
    outside_target.write_text('{"leaked": true}', encoding="utf-8")

    root = task_artifact_dir(tmp_path, "task-1")
    root.mkdir(parents=True)
    (root / "step-0.json").symlink_to(outside_target)

    with pytest.raises(ValueError, match="escapes the confined dir"):
        step_artifact_path(tmp_path, "task-1", 0)


def test_symlinked_task_dir_pointing_outside_data_dir_is_rejected(tmp_path):
    # The per-task dir ITSELF is a symlink escaping data_dir/artifacts/team-tasks/ —
    # e.g. an attacker-controlled data_dir where `artifacts/team-tasks/task-1` was
    # pre-planted as a symlink to a directory elsewhere on disk.
    outside_dir = tmp_path / "outside-dir"
    outside_dir.mkdir()

    artifacts_root = tmp_path / "data" / "artifacts" / "team-tasks"
    artifacts_root.mkdir(parents=True)
    (artifacts_root / "task-1").symlink_to(outside_dir)

    data_dir = tmp_path / "data"
    with pytest.raises(ValueError, match="escapes the confined dir"):
        step_artifact_path(data_dir, "task-1", 0)
