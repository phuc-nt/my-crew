"""Office room SSE — MULTI-SUBSCRIBER store-tail (v12 M29), NOT `stream_run`'s
single-drain (`my_crew/server/run_manager.py`/`sse_stream.py`, untouched by this module).

`stream_run` refuses a second concurrent attach to a still-running run (409) because it
drains a single in-proc queue with exactly one live consumer. That model cannot serve
this room: the room's writers (coordinator ticker, step workers, admin ops agent) are
SEPARATE OS processes, so there is no in-proc queue to drain in the first place — the
only channel is `office_room_store` (SQLite). Each client here owns its OWN cursor
(`since_seq`) and polls the store independently; N clients on the same room never
contend, so there is no 409 to raise.

Resume: a reconnecting `EventSource` sends `Last-Event-ID` (the browser's own built-in
behavior) with the last `id` it saw; a fresh client may pass `?since_seq=`. Either way
`list(room_id, since_seq)` returns exactly the rows after that cursor — no replay of
already-seen rows, no gap (the store's `seq` is the total-order key, not `ts`).

Each poll runs a synchronous sqlite read (`OfficeRoomStore.list`) directly on the event
loop, not offloaded to a thread: accepted at CEO-scale traffic — WAL mode means readers
never block on the room's writers, the query is indexed on `(room_id, seq)`, and a
single read is sub-millisecond, so it does not starve other coroutines on the loop.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from my_crew.config.settings import DATA_DIR
from my_crew.runtime.office_room_store import OfficeRoomStore, office_room_db_path

router = APIRouter(tags=["office"])

#: Store-tail poll cadence — fine for a chat/3D-driving stream on a single-server
#: deployment (see phase's "Unresolved questions": tune later if needed).
_POLL_INTERVAL_S = 1.0


def _store() -> OfficeRoomStore:
    return OfficeRoomStore(office_room_db_path(DATA_DIR))


@router.get("/api/office/rooms")
async def list_rooms() -> dict:
    """Every room id that has at least one message so far."""
    store = _store()
    try:
        return {"rooms": store.list_rooms()}
    finally:
        store.close()


@router.get("/api/office/rooms/{room_id}/stream")
async def stream_room(room_id: str, request: Request) -> EventSourceResponse:
    """SSE store-tail for one room: poll `office_room_store.list` ~1s, emit new rows.

    Cursor resolution: `Last-Event-ID` header (browser auto-resume) wins over
    `?since_seq=` (fresh-connect query param) wins over `?tail=N` (cold connect —
    replay only the LAST N rows) wins over 0 (from the beginning). The aggregated
    `office` room accumulates every mirrored event forever, so a full replay on first
    open grows without bound — clients that only need "what's happening now" (the
    live feed / 3D desks) should pass `tail`.
    """
    since_seq = _initial_cursor(request)
    if since_seq is None:
        since_seq = _tail_cursor(room_id, request)
    return EventSourceResponse(_tail(room_id, since_seq, request))


def _initial_cursor(request: Request) -> int | None:
    """Explicit cursor from the client, or None when neither channel provided one."""
    last_event_id = request.headers.get("last-event-id")
    if last_event_id is not None:
        try:
            return int(last_event_id)
        except ValueError:
            pass
    raw = request.query_params.get("since_seq")
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            pass
    return None


def _tail_cursor(room_id: str, request: Request) -> int:
    """Cursor for a cold connect: `?tail=N` skips everything but the last N rows.

    A malformed or non-positive `tail` falls back to full replay (0) — same tolerant
    posture as `_initial_cursor`, never a 4xx over a cosmetic param.
    """
    raw = request.query_params.get("tail")
    if raw is None:
        return 0
    try:
        n = int(raw)
    except ValueError:
        return 0
    if n <= 0:
        return 0
    store = _store()
    try:
        return max(0, store.last_seq(room_id) - n)
    finally:
        store.close()


async def _tail(room_id: str, since_seq: int, request: Request):
    """Disconnect-safe poll loop: stop cleanly the moment the client goes away instead
    of polling the store forever after nobody is listening — each SSE connection here
    is its own asyncio task, so a leaked one is a real (if small) per-connection cost.

    Frames carry NO `event:` field — `kind` rides INSIDE the JSON `data` payload
    instead, matching `sse_events.py`'s convention for the run stream. A browser
    `EventSource`'s `onmessage` handler fires ONLY for unnamed (default `message`-type)
    frames; a named `event: <kind>` frame is invisible to `onmessage` and requires a
    per-kind `addEventListener` the frontend does not register. `id:` (the row's `seq`)
    is unaffected — Last-Event-ID resume still works either way.
    """
    store = _store()
    cursor = since_seq
    try:
        while True:
            if await request.is_disconnected():
                return
            for msg in store.list(room_id, cursor):
                yield {
                    "id": str(msg.seq),
                    "data": json.dumps(
                        {"seq": msg.seq, "ts": msg.ts, "author": msg.author,
                         "kind": msg.kind, "body": msg.body,
                         "source_room_id": msg.source_room_id},
                        ensure_ascii=False,
                    ),
                }
                cursor = msg.seq
            await asyncio.sleep(_POLL_INTERVAL_S)
    finally:
        store.close()


# `room_id` validity is intentionally not enforced against a fixed set here — an
# unknown/empty room id just polls forever with zero rows, which is a harmless no-op
# (mirrors office_room_store.list's own tolerant behavior); raising 404 would require
# a room registry this module has no reason to own.
