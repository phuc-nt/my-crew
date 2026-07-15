"""Outputs hub + team-task board routes (v33 P3). STRICTLY read-only.

The office screen shows artifacts per-room only; this module is the cross-room
answer to "mọi kết quả nằm đâu?":

- `GET /api/outputs` — one flat index of every delivered step artifact (status done,
  step_type work/rework — the same filter the office Kết quả column applies) plus
  every exported file sitting in an agent's gateway artifact dir (the xlsx-email
  precedent), filterable by agent / recency.
- `GET /api/outputs/step/{task_id}/{seq}` — full result_text of one step; delegates
  to the office artifact route (one implementation of the 404-on-anything-odd rule).
- `GET /api/outputs/file/{agent_id}/{name}` — download of one exported file.
  Path-confined: agent_id must exist in the registry, `name` must be a bare filename
  (no separators), and the resolved path must stay inside that agent's artifact dir
  (symlink-safe via resolve + is_relative_to).
- `GET /api/team-tasks/board` — team tasks grouped into kanban lanes. Read-only:
  moving a card goes through the existing chat-command/gateway path, never here.
  Cancelled tasks are NOT shown (list_recent_tasks excludes them); the side lane
  `khac` holds stalled tasks only.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["outputs"])

_INDEX_TASK_LIMIT = 200
_DELIVERED_TYPES = ("work", "rework")
#: Kanban lanes in display order; stalled/cancelled roll into the side lane.
_BOARD_LANES = ("planning", "open", "running", "done", "khac")


def _open_store():
    from src.runtime.team_task_paths import team_tasks_db_path
    from src.runtime.team_task_store import TeamTaskStore

    return TeamTaskStore(team_tasks_db_path())


@router.get("/outputs")
def list_outputs(agent: str = Query(""), days: int = Query(0, ge=0),
                 limit: int = Query(100, ge=1, le=500)) -> dict:
    """Flat newest-first index of delivered outputs. Metadata only — content stays
    behind the per-item endpoints."""
    import datetime as _dt

    cutoff = None
    if days > 0:
        cutoff = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(days=days)).isoformat()

    items: list[dict] = []
    store = _open_store()
    try:
        tasks = store.list_recent_tasks(_INDEX_TASK_LIMIT)
    finally:
        store.close()
    for t in tasks:
        for s in t.steps:
            if s.status != "done" or s.step_type not in _DELIVERED_TYPES:
                continue
            if agent and s.assigned_to != agent:
                continue
            ts = s.last_seen or s.spawned_at or t.created_at
            # The days filter applies to the ITEM's own timestamp (when the step
            # delivered), not the task's creation date — an old task can deliver
            # yesterday (review M3).
            if cutoff and ts < cutoff:
                continue
            items.append({
                "kind": "step",
                "task_id": t.id, "task_title": t.title,
                "room_id": t.room_id or t.id,
                "seq": s.seq, "step_title": s.title,
                "agent_id": s.assigned_to,
                "ts": ts,
            })

    items.extend(f for f in _exported_files(agent) if not cutoff or f["ts"] >= cutoff)
    items.sort(key=lambda i: i["ts"], reverse=True)
    truncated = len(items) > limit
    return {"items": items[:limit], "truncated": truncated}


def _exported_files(agent_filter: str) -> list[dict]:
    """Files agents exported through the gateway artifact dir (xlsx-email precedent):
    `<agent data_dir>/artifacts/*` — flat scan, files only, no recursion. A missing
    or unreadable dir contributes nothing (never fails the index)."""
    import datetime as _dt

    from src.runtime.agent_paths import agent_data_dir
    from src.runtime.registry import load_registry

    out: list[dict] = []
    try:
        entries = load_registry()
    except Exception:  # noqa: BLE001 — registry unreadable: step index still works
        return out
    for entry in entries:
        if agent_filter and entry.id != agent_filter:
            continue
        art_dir = agent_data_dir(entry.id) / "artifacts"
        try:
            files = [p for p in art_dir.iterdir() if p.is_file()]
        except OSError:
            continue
        for p in files:
            try:
                stat = p.stat()  # one stat; a file deleted mid-scan just drops out
            except OSError:
                continue
            out.append({
                "kind": "file", "agent_id": entry.id, "name": p.name,
                "size": stat.st_size,
                "ts": _dt.datetime.fromtimestamp(stat.st_mtime, tz=_dt.UTC).isoformat(),
                "task_id": "", "task_title": "", "room_id": "",
                "seq": 0, "step_title": "",
            })
    return out


@router.get("/outputs/step/{task_id}/{seq}")
def get_output_step(task_id: str, seq: int) -> dict:
    """One step's full result — same implementation as the office artifact viewer."""
    from src.server.routes_office_artifacts import get_step_artifact

    return get_step_artifact(task_id, seq)


@router.get("/outputs/file/{agent_id}/{name}")
def download_output_file(agent_id: str, name: str) -> FileResponse:
    """Download ONE exported file. Confinement: registry-known agent, bare filename,
    resolved path inside that agent's artifact dir."""
    from src.runtime.agent_paths import agent_data_dir
    from src.runtime.registry import load_registry

    try:
        known = {e.id for e in load_registry()}
    except Exception:  # noqa: BLE001
        known = set()
    if agent_id not in known:
        raise HTTPException(status_code=404, detail="không tìm thấy nhân sự")
    if "/" in name or "\\" in name or name in (".", "..") or not name:
        raise HTTPException(status_code=404, detail="tên file không hợp lệ")

    art_dir = (agent_data_dir(agent_id) / "artifacts").resolve()
    target = (art_dir / name).resolve()
    # resolve() follows symlinks BEFORE the containment check, so a symlink pointing
    # outside the artifact dir fails is_relative_to and reads as absent.
    if not target.is_relative_to(art_dir) or not target.is_file():
        raise HTTPException(status_code=404, detail="không tìm thấy file")
    return FileResponse(
        path=target, filename=name, media_type="application/octet-stream",
        content_disposition_type="attachment",
    )


@router.get("/team-tasks/board")
def team_task_board() -> dict:
    """Kanban lanes over team tasks (read-only). planning drafts get their own lane
    so the CEO sees what still awaits confirm; stalled tasks land in `khac`
    (cancelled ones are excluded upstream — an abandoned draft is not board noise)."""
    store = _open_store()
    try:
        tasks = store.list_recent_tasks(_INDEX_TASK_LIMIT, include_planning=True)
    finally:
        store.close()
    lanes: dict[str, list[dict]] = {lane: [] for lane in _BOARD_LANES}
    for t in tasks:
        done = sum(1 for s in t.steps if s.status == "done")
        # v50: how many steps declared needs_shell (v45) — those escalate to the deep_agent
        # (Docker sandbox) tier; the rest run create_agent (no Docker). Surfaces which tasks
        # depend on the sandbox at a glance.
        needs_shell = sum(1 for s in t.steps if getattr(s, "needs_shell", False))
        card = {
            "task_id": t.id, "title": t.title, "pic_id": t.pic_id,
            "room_id": t.room_id or t.id, "status": t.status,
            "created_at": t.created_at,
            "steps_done": done, "steps_total": len(t.steps),
            "steps_needs_shell": needs_shell,
        }
        lane = t.status if t.status in lanes else "khac"
        lanes[lane].append(card)
    return {"lanes": [{"id": lane, "cards": lanes[lane]} for lane in _BOARD_LANES]}


#: v50: the per-step-attempt telemetry fields safe to surface for a task cost breakdown — an
#: explicit allowlist (the visualize_views discipline: select fields, never echo the raw row).
_COST_FIELDS = (
    "step_id", "agent_id", "engine", "status", "step_type",
    "cost_usd", "cost_source", "input_tokens", "output_tokens", "duration_ms",
)


@router.get("/team-tasks/{task_id}/cost")
def team_task_cost(task_id: str) -> dict:
    """v50: per-step cost + token breakdown for one team task (read-only, allowlisted).

    Wraps `CaptureStore.list_for_task` (one row per step-attempt) into a projected list plus
    task totals, so the FE can attribute cost to a specific task/step instead of only the
    monthly-per-agent view. Cost may be None (dry-run) — totals sum the known values only.
    """
    from src.runtime.capture_store import CaptureStore
    from src.runtime.team_task_paths import capture_db_path

    path = capture_db_path()
    if not path.exists():
        return {"task_id": task_id, "steps": [], "total_cost_usd": 0.0,
                "total_input_tokens": 0, "total_output_tokens": 0}
    store = CaptureStore(path)
    try:
        rows = store.list_for_task(task_id)
    finally:
        store.close()
    steps = [{k: r.get(k) for k in _COST_FIELDS} for r in rows]
    return {
        "task_id": task_id,
        "steps": steps,
        "total_cost_usd": round(sum(r.get("cost_usd") or 0.0 for r in rows), 6),
        "total_input_tokens": sum(r.get("input_tokens") or 0 for r in rows),
        "total_output_tokens": sum(r.get("output_tokens") or 0 for r in rows),
    }
