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
#: Step types whose artifact is a deliverable the CEO should be able to find. "sprint"
#: (v77) belongs here for the strongest reason of all: a sprint task has exactly ONE
#: content step, so its artifact is not merely part of the output — it IS the output.
_DELIVERED_TYPES = ("work", "sprint", "rework")
#: Kanban lanes in display order; stalled/cancelled roll into the side lane.
_BOARD_LANES = ("planning", "open", "running", "done", "khac")


def _open_store():
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

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

    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.registry import load_registry

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
    from my_crew.server.routes_office_artifacts import get_step_artifact

    return get_step_artifact(task_id, seq)


@router.get("/outputs/file/{agent_id}/{name}")
def download_output_file(agent_id: str, name: str) -> FileResponse:
    """Download ONE exported file. Confinement: registry-known agent, bare filename,
    resolved path inside that agent's artifact dir."""
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.registry import load_registry

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
    # v58 P2 (queue transparency): ticker phục vụ task CŨ NHẤT có action trước
    # (list_dispatchable = open/running ORDER BY created_at, 1 action/tick 60s) — một
    # task đứng sau N task cũ hơn thì chờ ~N tick trong im lặng. Tính vị trí từ CHÍNH
    # danh sách đã fetch (không thêm query); field optional nên client cũ không vỡ.
    dispatchable = sorted(
        (t for t in tasks if t.status in ("open", "running")),
        key=lambda x: x.created_at,
    )
    queue_position = {t.id: i for i, t in enumerate(dispatchable)}
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
        if t.id in queue_position:
            card["queue_position"] = queue_position[t.id]
        if t.status == "stalled":
            # v88 P3: the title of the first dead/failed step, so the stuck-task panel
            # on the board/detail page can say WHY without a second request. Same
            # predicate `ops_stalled_task._dead_steps` uses (failed/timeout) — a
            # review-exhausted stall (no dead step, newest review failed) has none of
            # these and the field is simply absent; the FE falls back to a generic
            # "đang chờ xử lý" line for that case.
            dead = next((s for s in t.steps if s.status in ("failed", "timeout")), None)
            if dead is not None:
                card["stalled_step"] = dead.title
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
    from my_crew.runtime.capture_store import CaptureStore
    from my_crew.runtime.team_task_paths import capture_db_path

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


#: v82: route-decision fields safe to surface — allowlist like `_COST_FIELDS`
#: (`signals` stays internal: raw keyword matches over the brief, noise for the CEO).
_ROUTE_FIELDS = ("mode", "source", "reason")


@router.get("/team-tasks/{task_id}/route")
def team_task_route(task_id: str) -> dict:
    """v82: the persisted sprint/team routing decision for one task (read-only).

    Empty fields — never 404 — when the task is unknown or predates route_json,
    matching the cost endpoint's discipline (absence is a normal state, not an error).
    """
    store = _open_store()
    try:
        route = store.get_route(task_id) or {}
    finally:
        store.close()
    return {"task_id": task_id,
            **{k: str(route.get(k) or "") for k in _ROUTE_FIELDS}}


@router.get("/team-tasks/{task_id}/metrics")
def team_task_metrics(task_id: str) -> dict:
    """v82: wall-clock + step-mix metrics for one task (read-only, store-only).

    Wraps `bench.task_metrics.load_task_metric` WITHOUT `data_dir`: per-step
    transcript decomposition would need each step's acting agent's data dir (steps
    fan out across agents), and the badge/detail surface only needs the store-side
    numbers. Wall-clock includes queue wait by design — it is the CEO's experienced
    latency, not pure compute time. 404 when the task is not in the store (unlike
    /route, there is no meaningful all-empty metric shape).
    """
    from my_crew.bench.task_metrics import load_task_metric
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    db_path = team_tasks_db_path()
    metric = load_task_metric(db_path, task_id) if db_path.exists() else None
    if metric is None:
        raise HTTPException(status_code=404, detail="không thấy task")
    return {
        "task_id": metric.task_id,
        "mode": metric.mode,
        "status": metric.status,
        "wall_clock_seconds": metric.wall_clock_seconds,
        "wall_clock_text": metric.wall_clock_text,
        "cost_usd": metric.cost_usd,
        "step_count": metric.step_count,
        "content_steps": metric.content_steps,
        "review_steps": metric.review_steps,
        "rework_steps": metric.rework_steps,
        "steps": [
            {"seq": s.seq, "step_type": s.step_type, "status": s.status,
             "cost_usd": s.cost_usd, "seconds": s.seconds}
            for s in metric.steps
        ],
    }
