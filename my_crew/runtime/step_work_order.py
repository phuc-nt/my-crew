"""Per-attempt work-order — the frozen STEP-LEVEL input of one team-step run (v80 P2).

`data_dir/artifacts/team-tasks/<task_id>/work-orders/<step_id>-<attempt_id>.json`,
written best-effort right after the runner has loaded the step's inputs and resolved
the effective runtime kind, BEFORE the tier runs. DRY with the transcript (Phase 1):
the transcript keeps the verbatim messages (`llm_request` events); the work-order keeps
the step-level input + resolved config + a POINTER to the transcript — nothing stored
twice. Messages are NOT here because they are assembled inside each tier at run time.

One-way snapshot convention: the work-order is a photograph of the attempt's input at
spawn time. Later store amendments (reassign, guidance appends, plan amend) do NOT
update it — replay reproduces what the attempt SAW, not what the row says today.

Same contract as the recorder: writing must never break the step (all errors swallowed,
one warning), and the whole feature is gated on `settings.step_transcripts`.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from my_crew.runtime.step_recorder import _SEGMENT_RE, scrub_secrets

logger = logging.getLogger(__name__)

WORK_ORDER_VERSION = 1


def work_orders_dir(data_dir: Path, task_id: str) -> Path:
    """`data_dir/artifacts/team-tasks/<task_id>/work-orders/` — path-confined via
    `task_artifact_dir` exactly like the sibling `transcripts/` dir."""
    from my_crew.agent.team_task_artifact import task_artifact_dir

    return task_artifact_dir(data_dir, task_id) / "work-orders"


def work_order_path(data_dir: Path, task_id: str, step_id: str, attempt_id: str) -> Path:
    """The one work-order file for a (step, attempt). Raises ValueError on unsafe ids."""
    for segment in (step_id, attempt_id):
        if not _SEGMENT_RE.match(segment):
            raise ValueError(f"unsafe work-order path segment: {segment!r}")
    return work_orders_dir(data_dir, task_id) / f"{step_id}-{attempt_id}.json"


def write_work_order(
    settings: Any,
    *,
    task_id: str,
    step: Any,
    attempt_id: str,
    effective_kind: str,
    task_title: str = "",
    plan_hash: str = "",
    original_request: str = "",
    guidance: str = "",
) -> None:
    """Freeze one attempt's step-level input to disk. Best-effort: any failure is one
    warning, never an exception into the step run.

    The handoff text (the deps' artifacts as the attempt will read them) is captured
    HERE, at spawn time — the graph's own `perceive` re-reads the same artifacts
    moments later, so the two match unless a dep re-runs mid-attempt (accepted)."""
    if not getattr(settings, "step_transcripts", True):
        return
    try:
        step_id = str(getattr(step, "step_id", "") or "")
        path = work_order_path(
            Path(getattr(settings, "data_dir", "")), task_id, step_id, attempt_id
        )
        handoff = ""
        try:
            from my_crew.agent.team_task_graph import _read_deps_handoff
            from my_crew.runtime.team_task_paths import team_tasks_root

            # The deps read resolves the SHARED task store and the shared step
            # artifacts, so it takes `team_tasks_root()` — not this agent's own
            # `data_dir`, which holds only its transcripts and work orders and would
            # resolve an empty store, recording `handoff: ""` for every step that has
            # deps. The path above stays per-agent on purpose (same as transcripts).
            handoff = _read_deps_handoff(
                team_tasks_root(), task_id,
                tuple(getattr(step, "deps", ()) or ()),
            )
        except Exception:  # noqa: BLE001 — a broken deps read degrades to "" handoff
            logger.warning("work-order %s/%s: deps handoff read failed", task_id, step_id,
                           exc_info=True)

        from my_crew.config.settings import MODEL_ROLES

        order = {
            "version": WORK_ORDER_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "task_id": task_id,
            "task_title": task_title,
            "plan_hash": plan_hash,
            "original_request": original_request,
            "step_id": step_id,
            "step_seq": int(getattr(step, "seq", 0) or 0),
            "step_title": str(getattr(step, "title", "") or ""),
            "assigned_to": str(getattr(step, "assigned_to", "") or ""),
            "attempt_id": attempt_id,
            "step_type": str(getattr(step, "step_type", "work") or "work"),
            "acceptance": str(getattr(step, "acceptance", "") or ""),
            "needs_web": bool(getattr(step, "needs_web", False)),
            "needs_shell": bool(getattr(step, "needs_shell", False)),
            "intervention_count": int(getattr(step, "intervention_count", 0) or 0),
            "deps": list(getattr(step, "deps", ()) or ()),
            "handoff": handoff,
            "guidance": guidance,
            "effective_runtime": effective_kind,
            # Snapshot of role → model chain AT RUN TIME, via the same resolve API
            # `LlmClient.complete(role=...)` uses — the drift replay must surface.
            "model_roles": {
                role: list(settings.model_for_role(role)) for role in MODEL_ROLES
            },
            "transcript": f"transcripts/{step_id}-{attempt_id}.jsonl",
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            scrub_secrets(json.dumps(order, ensure_ascii=False, indent=2, default=str)),
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception:  # noqa: BLE001 — observation must never break the step
        logger.warning("work-order write failed for %s attempt %s", task_id, attempt_id,
                       exc_info=True)


def load_work_order(
    data_dir: Path, task_id: str, step_id: str, attempt_id: str | None = None,
) -> dict[str, Any]:
    """Load one work-order. Without `attempt_id`, the NEWEST (mtime) order for the step
    is used — attempt ids are UUIDs with no ordering of their own. Raises
    FileNotFoundError with an operator-readable message when nothing matches."""
    if attempt_id is not None:
        path = work_order_path(data_dir, task_id, step_id, attempt_id)
        if not path.is_file():
            raise FileNotFoundError(
                f"không có work-order cho {task_id}/{step_id} attempt {attempt_id} "
                f"(tìm ở {path})"
            )
        return json.loads(path.read_text(encoding="utf-8"))
    if not _SEGMENT_RE.match(step_id):
        raise ValueError(f"unsafe work-order path segment: {step_id!r}")
    candidates = sorted(
        work_orders_dir(data_dir, task_id).glob(f"{step_id}-*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates:
        raise FileNotFoundError(
            f"không có work-order nào cho {task_id}/{step_id} — bước này chạy trước v80 "
            "hoặc STEP_TRANSCRIPTS đang tắt"
        )
    return json.loads(candidates[-1].read_text(encoding="utf-8"))
