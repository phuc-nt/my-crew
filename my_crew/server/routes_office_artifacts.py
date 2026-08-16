"""Read-only artifact routes (v17) — the office screen's "Kết quả" column.

Opens the step handoff artifacts (`step-<seq>.json`, written by `deliver` since v12)
to the UI: a per-room catalog + the full `result_text` of one step. STRICTLY read-only.

Path safety: nothing from the client ever reaches the filesystem directly — `task_id`
must resolve through `store.get()` (row must exist), `seq` is int-coerced by FastAPI
(anything else 422s), and the file path is built exclusively by
`team_task_artifact.step_artifact_path` (which itself re-validates/confines — see that
module). Any read/lookup failure is a clean 404, never a 500 leaking internals.

Routes live under `/api` (AuthMiddleware-protected — NOT in `_PUBLIC_PREFIXES`).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/office", tags=["office-artifacts"])


@router.get("/rooms/{room_id}/artifacts")
def get_room_artifacts(room_id: str) -> dict:
    """Catalog of every task in the workroom + ALL its steps (id/title/assignee/
    status/seq/step_type). The FE's Kết quả column filters to
    `status=='done' AND step_type in ('work','rework')` — a review-step's verdict
    lives in a different file and has no `step-<seq>.json` (red-team M1), and this
    API deliberately returns the full step list so future progress views need no new
    endpoint."""
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    try:
        tasks = store.tasks_in_room(room_id)
    finally:
        store.close()
    return {"tasks": [
        {
            "task_id": t.id, "title": t.title, "pic_id": t.pic_id, "status": t.status,
            "steps": [
                {"step_id": s.step_id, "title": s.title, "assigned_to": s.assigned_to,
                 "status": s.status, "seq": s.seq,
                 "step_type": getattr(s, "step_type", "work")}
                for s in t.steps
            ],
        }
        for t in tasks
    ]}


@router.get("/tasks/{task_id}/steps/{seq}/artifact")
def get_step_artifact(task_id: str, seq: int) -> dict:
    """Full result of ONE step — the artifact viewer's payload.

    404 on: unknown task, seq not belonging to the task, artifact file not written
    yet (step not delivered), or ANY validation error from the path layer (a legacy/
    hand-seeded task_id that fails the artifact module's own charset gate must read
    as "not found", not a 500)."""
    from my_crew.agent.team_task_artifact import read_step_artifact
    from my_crew.runtime.team_task_paths import team_tasks_db_path, team_tasks_root
    from my_crew.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    try:
        task = store.get(task_id)
    finally:
        store.close()
    if task is None:
        raise HTTPException(status_code=404, detail="không tìm thấy việc")
    step = next((s for s in task.steps if s.seq == seq), None)
    if step is None:
        raise HTTPException(status_code=404, detail="bước không thuộc việc này")

    try:
        artifact = read_step_artifact(team_tasks_root(), task_id, seq)
    except Exception:  # noqa: BLE001 — any path/validation hiccup reads as absent
        logger.warning("artifact read failed for %s/%s", task_id, seq, exc_info=True)
        artifact = None
    if artifact is None:
        raise HTTPException(status_code=404, detail="bước này chưa có kết quả bàn giao")
    # `.get()` throughout: an outcome-fallback artifact (worker crash path) may lack
    # fields a happy-path artifact always carries.
    return {
        "task_id": task_id,
        "step_title": str(artifact.get("step_title") or step.title),
        "result_text": str(artifact.get("result_text") or ""),
        "attempt": str(artifact.get("attempt") or ""),
        "self_check_failed": bool(artifact.get("self_check_failed", False)),
    }


@router.get("/tasks/{task_id}/steps/{seq}/transcript")
def get_step_transcript(task_id: str, seq: int) -> dict:
    """v82: the step attempt's process transcript (v80 recorder) — the viewer's
    "Quá trình" tab. Read-only, parsed JSONL events verbatim (already secret-scrubbed
    and head-capped at write time).

    Transcripts live under the ACTING agent's isolated data dir
    (`.data/agents/<assigned_to>/artifacts/team-tasks/<task>/transcripts/`), not the
    shared team-tasks root — the worker records into its own jail. A step retried
    several times has several files; the newest (by mtime) is the one shown.
    404 on: unknown task/seq, malformed actor id, or no transcript file (recorder
    off / step predates v80) — absence is never a 500."""
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.step_recorder import transcripts_dir
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore
    from my_crew.runtime.transcript_evidence import parse_transcript_events

    store = TeamTaskStore(team_tasks_db_path())
    try:
        task = store.get(task_id)
    finally:
        store.close()
    if task is None:
        raise HTTPException(status_code=404, detail="không tìm thấy việc")
    step = next((s for s in task.steps if s.seq == seq), None)
    if step is None:
        raise HTTPException(status_code=404, detail="bước không thuộc việc này")

    try:
        files = sorted(
            transcripts_dir(agent_data_dir(step.assigned_to), task_id)
            .glob(f"{step.step_id}-*.jsonl"),
            key=lambda p: p.stat().st_mtime,
        )
    except Exception:  # noqa: BLE001 — bad actor id / IO hiccup reads as absent
        logger.warning("transcript lookup failed for %s/%s", task_id, seq, exc_info=True)
        files = []
    if not files:
        raise HTTPException(status_code=404, detail="bước này chưa có transcript")
    events = parse_transcript_events(files[-1])
    if not events:
        raise HTTPException(status_code=404, detail="bước này chưa có transcript")
    return {"task_id": task_id, "step_id": step.step_id, "seq": seq,
            "attempts": len(files), "events": events}
