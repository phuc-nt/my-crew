"""Run routes (v2 M2-P6): POST /api/agents/{id}/trigger (start an in-process run).

The /api/runs/{run_id}/stream SSE route is added here in Slice 3. This slice only
starts a run and returns its run_id + thread_id; the events accumulate in the run's
queue until the stream route drains them.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from src.server import agent_views
from src.server.run_manager import CapReachedError, SameThreadRunningError
from src.server.sse_stream import stream_run

router = APIRouter(tags=["runs"])

_VALID_KINDS = {"daily", "weekly", "okr", "resource"}
_VALID_AUDIENCES = {"internal", "external"}


def _manager(request: Request):
    return request.app.state.run_manager


@router.post("/api/agents/{agent_id}/trigger")
async def trigger_run(agent_id: str, request: Request) -> dict:
    """Start an on-demand in-process report run; return {run_id, thread_id}.

    Params (JSON body or query): kind (default daily), audience (default internal),
    dry_run (optional bool). 404 unknown agent; 409 same (agent,thread) already
    running; 503 over the global cap.
    """
    params = await _read_params(request)
    kind = params.get("kind", "daily")
    audience = params.get("audience", "internal")
    dry_run = bool(params.get("dry_run", False))

    if kind not in _VALID_KINDS:
        raise HTTPException(status_code=422, detail=f"invalid kind {kind!r}")
    # Validate audience strictly (not silent-coerce): a typo'd "external" must NOT
    # quietly downgrade to internal and bypass the Lớp B approval gate.
    if audience not in _VALID_AUDIENCES:
        raise HTTPException(status_code=422, detail=f"invalid audience {audience!r}")
    if agent_id not in {e.id for e in agent_views.load_registry()}:
        raise HTTPException(status_code=404, detail=f"unknown agent {agent_id!r}")

    try:
        handle = _manager(request).start(agent_id, kind, audience, dry_run)
    except SameThreadRunningError:
        raise HTTPException(status_code=409, detail="a run for this thread is active") from None
    except CapReachedError:
        raise HTTPException(status_code=503, detail="server at run capacity") from None
    return {"run_id": handle.run_id, "thread_id": handle.thread_id}


@router.get("/api/runs/{run_id}/stream")
async def stream(run_id: str, request: Request) -> EventSourceResponse:
    """SSE: stream a run's live node-progress + a terminal event.

    404 unknown run_id; 409 if a live stream is already draining a still-running run
    (single-drain — a late attach after the run finished is always allowed).
    """
    handle = _manager(request).get(run_id)
    if handle is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    if handle.attached and handle.status != "terminal":
        raise HTTPException(status_code=409, detail="run already being streamed")
    return EventSourceResponse(stream_run(handle))


async def _read_params(request: Request) -> dict:
    """Merge query params with a JSON body (body wins). Tolerates an empty/no body."""
    params = dict(request.query_params)
    try:
        body = await request.json()
        if isinstance(body, dict):
            params.update(body)
    except Exception:  # noqa: BLE001 — no/invalid body is fine; query params still apply
        pass
    return params
