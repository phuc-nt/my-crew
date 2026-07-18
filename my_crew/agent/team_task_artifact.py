"""Handoff-artifact helper for the team-task execution graph (v12 M28a).

Each step writes its output to `data_dir/artifacts/team-tasks/<task-id>/step-<n>.json`
so the NEXT step (possibly on a different agent/process) can read it as its `perceive`
input. Internal-only, no egress, no gateway involvement (THE INVARIANT) — this is a
handoff between graph steps, not a delivery.

Two hazards this module exists to close:
  1. **Path traversal.** `task_id`/`step_seq` must never let a caller escape the
     per-task artifact dir (e.g. a task id like `../../etc`). Every write/read resolves
     the final path and verifies it is still inside the confined root.
  2. **Torn reads.** A reader (the next step, or P3's poller) must never see a
     PARTIAL JSON file mid-write. Writes go to a `.tmp` sibling then `os.replace`
     (atomic on POSIX + Windows NTFS), so a reader either sees the old file, the new
     complete file, or (briefly) nothing — never a half-written one.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

#: A task id is a caller-minted identifier (the coordinator's uuid/slug) — validated
#: the same way `agent_paths` validates an agent id: single safe path segment.
_TASK_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def _validate_task_id(task_id: str) -> str:
    if not _TASK_ID_RE.match(task_id):
        raise ValueError(
            f"Invalid team task id {task_id!r}: must match {_TASK_ID_RE.pattern} "
            "(alnum, '-'/'_', no '/' or '..')."
        )
    return task_id


def task_artifact_dir(data_dir: Path, task_id: str) -> Path:
    """`data_dir/artifacts/team-tasks/<task-id>/` — the confinement root for one task."""
    return data_dir / "artifacts" / "team-tasks" / _validate_task_id(task_id)


def step_artifact_path(data_dir: Path, task_id: str, step_seq: int) -> Path:
    """The on-disk path for one step's handoff artifact: `step-<n>.json`."""
    unresolved_base = data_dir / "artifacts" / "team-tasks"
    root = task_artifact_dir(data_dir, task_id)
    path = root / f"step-{int(step_seq)}.json"
    _confine(path, root, unresolved_base)
    return path


def review_verdict_artifact_path(
    data_dir: Path, task_id: str, parent_seq: int, review_round: int
) -> Path:
    """The on-disk path for a peer-review verdict artifact:
    `step-<parent_seq>-review-<round>.json` (M32). `round` is baked into the filename
    (not overwritten in place) so a round-2 re-review's verdict never clobbers
    round-1's — `tick_actions`'s round-cap logic reads BOTH files across the task's
    lifetime, not just the latest. Same path-confinement guard as `step_artifact_path`."""
    unresolved_base = data_dir / "artifacts" / "team-tasks"
    root = task_artifact_dir(data_dir, task_id)
    path = root / f"step-{int(parent_seq)}-review-{int(review_round)}.json"
    _confine(path, root, unresolved_base)
    return path


def write_review_verdict_artifact(
    data_dir: Path, task_id: str, parent_seq: int, review_round: int, payload: dict[str, Any]
) -> Path:
    """Write a peer-review verdict artifact — same atomic temp-then-rename discipline
    as `write_step_artifact`."""
    path = review_verdict_artifact_path(data_dir, task_id, parent_seq, review_round)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f".tmp-{os.getpid()}")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)
    return path


def read_review_verdict_artifact(
    data_dir: Path, task_id: str, parent_seq: int, review_round: int
) -> dict[str, Any] | None:
    """Read a peer-review verdict artifact — same tolerant-of-absence/corruption
    contract as `read_step_artifact`."""
    path = review_verdict_artifact_path(data_dir, task_id, parent_seq, review_round)
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _confine(path: Path, root: Path, unresolved_base: Path) -> Path:
    """Resolve `path` and verify it stays inside `unresolved_base` (dereferences
    symlinks — a symlink inside the dir pointing OUT is caught by the resolved-prefix
    check, same posture as `hard_block.confined_xlsx_path`). Raises ValueError on any
    escape.

    Compares against `unresolved_base` (`data_dir/artifacts/team-tasks`, one level
    above the per-task dir) rather than `root` (the per-task dir itself): `root` may
    itself be a symlink whose target the caller does not fully control (e.g. a
    pre-planted `<task-id>` symlink pointing outside `data_dir`) — resolving `root`
    would then compare a path against itself and never detect the escape. Anchoring
    one level higher means the per-task dir's OWN symlink-ness is caught too, not
    just symlinks nested inside it.

    All paths are resolved with `strict=False` (none need exist yet — the artifact
    dir is created lazily on write) so the comparison is apples-to-apples even when a
    parent segment is itself a symlink (e.g. macOS `/var` → `/private/var`).
    """
    resolved = path.resolve(strict=False)
    resolved_base = unresolved_base.resolve(strict=False)
    if not resolved.is_relative_to(resolved_base):
        raise ValueError(f"artifact path {path} escapes the confined dir {unresolved_base}")
    return resolved


def write_step_artifact(
    data_dir: Path, task_id: str, step_seq: int, payload: dict[str, Any]
) -> Path:
    """Write `payload` as the step's handoff artifact — atomic temp-then-rename.

    The temp file is written in the SAME directory as the target (so `os.replace` is
    a same-filesystem rename, which is what makes it atomic) with a `.tmp-<seq>`
    suffix, then renamed over the final path. A reader can never observe a partial
    write: it sees either the prior artifact or the complete new one.
    """
    path = step_artifact_path(data_dir, task_id, step_seq)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f".tmp-{os.getpid()}")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)
    return path


def read_step_artifact(data_dir: Path, task_id: str, step_seq: int) -> dict[str, Any] | None:
    """Read a step's handoff artifact — tolerant of "not written yet" and of a
    corrupt/partial read (should not happen given atomic rename, but a reader must
    never crash on it): both return None rather than raising.
    """
    path = step_artifact_path(data_dir, task_id, step_seq)
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
