"""Office room SSE (v12 M29): multi-subscriber store-tail, resume-from-seq, auth gate.

Load-bearing:
- `_tail` is driven directly (like `test_server_stream.py` drives `stream_run` directly)
  since it is an infinite poll loop by design — a fake `Request.is_disconnected()` stops
  it after N iterations instead of sleeping through the real ~1s poll cadence.
- TWO independent generators reading the SAME room both see the SAME rows — no shared
  queue, no 409 (proves the multi-subscriber claim: store-tail, not `stream_run`'s
  single-drain model).
- `_initial_cursor` resolves `Last-Event-ID` over `?since_seq=` over 0 — a reconnect
  after N events resumes with NO gap and NO replay of already-seen rows.
- `/api/office/rooms` and the room stream route are gated by auth like every other
  non-public route (NOT in `auth._PUBLIC_PREFIXES`).
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from my_crew.runtime.office_room_store import OfficeRoomStore
from my_crew.server import routes_office_stream as ros


class _FakeRequest:
    """Disconnects after `max_polls` polls — lets `_tail`'s infinite loop terminate in
    a test without waiting through the real poll interval."""

    def __init__(self, *, max_polls: int, headers: dict | None = None, query: dict | None = None):
        self._polls_left = max_polls
        self.headers = headers or {}
        self.query_params = query or {}

    async def is_disconnected(self) -> bool:
        if self._polls_left <= 0:
            return True
        self._polls_left -= 1
        return False


async def _drain(room_id: str, since_seq: int, request) -> list[dict]:
    return [json.loads(frame["data"]) async for frame in ros._tail(room_id, since_seq, request)]


def test_tail_frames_carry_no_event_key(tmp_path):
    """Wire-contract pin: a browser `EventSource.onmessage` fires ONLY for unnamed
    (default `message`-type) SSE frames — a frame with an `event:` field is invisible
    to it. `_tail` must therefore never set `"event"` in its yielded dict; `kind` rides
    inside the JSON `data` payload instead (matching `sse_events.py`'s convention).
    A frame carrying an `event` key here would silently break the frontend even though
    every other suite (which drains `_tail` as a Python generator or mocks the hook
    wholesale) stays green."""
    _seed(tmp_path, 1)
    request = _FakeRequest(max_polls=1)

    async def _run():
        return [frame async for frame in ros._tail("t1", 0, request)]

    frames = asyncio.run(_run())
    assert len(frames) == 1
    assert "event" not in frames[0]
    payload = json.loads(frames[0]["data"])
    assert payload["kind"] == "ceo"


def _seed(tmp_path, n: int) -> None:
    store = OfficeRoomStore(tmp_path / "office_room.sqlite3")
    for i in range(n):
        store.append("t1", author="ceo", kind="ceo", body={"text": f"msg-{i}"})
    store.close()


@pytest.fixture(autouse=True)
def _office_db_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(ros, "DATA_DIR", tmp_path)
    return tmp_path


def test_tail_emits_seeded_rows_in_seq_order(tmp_path):
    _seed(tmp_path, 3)
    request = _FakeRequest(max_polls=1)
    events = asyncio.run(_drain("t1", 0, request))
    assert [e["body"]["text"] for e in events] == ["msg-0", "msg-1", "msg-2"]
    assert [e["seq"] for e in events] == [1, 2, 3]


def test_tail_since_seq_resumes_with_no_gap_no_replay(tmp_path):
    _seed(tmp_path, 5)
    request = _FakeRequest(max_polls=1)
    events = asyncio.run(_drain("t1", 3, request))
    assert [e["seq"] for e in events] == [4, 5]  # no replay of 1-3, no gap


def test_tail_empty_room_yields_nothing_and_stops_on_disconnect(tmp_path):
    request = _FakeRequest(max_polls=2)
    events = asyncio.run(_drain("t1", 0, request))
    assert events == []


def test_multi_subscriber_same_room_both_receive_same_events(tmp_path):
    """Two independent `_tail` generators over the SAME room — store-tail means each
    owns its own cursor and polls independently; both see identical rows, no 409."""
    _seed(tmp_path, 4)

    async def _run():
        req_a = _FakeRequest(max_polls=1)
        req_b = _FakeRequest(max_polls=1)
        events_a, events_b = await asyncio.gather(
            _drain("t1", 0, req_a), _drain("t1", 0, req_b),
        )
        return events_a, events_b

    events_a, events_b = asyncio.run(_run())
    assert len(events_a) == 4 and len(events_b) == 4
    assert [e["seq"] for e in events_a] == [e["seq"] for e in events_b]


def test_tail_picks_up_rows_appended_between_polls(tmp_path):
    """A row appended AFTER the generator starts but before it disconnects is still
    delivered — proves each poll iteration re-reads the store (not a one-shot snapshot)."""
    store = OfficeRoomStore(tmp_path / "office_room.sqlite3")
    store.append("t1", author="ceo", kind="ceo", body={"text": "first"})

    class _AppendingRequest(_FakeRequest):
        async def is_disconnected(self) -> bool:
            disconnected = await super().is_disconnected()
            if not disconnected and self._polls_left == 0:
                store.append("t1", author="ceo", kind="ceo", body={"text": "second"})
            return disconnected

    request = _AppendingRequest(max_polls=2)
    events = asyncio.run(_drain("t1", 0, request))
    store.close()
    assert [e["body"]["text"] for e in events] == ["first", "second"]


# --- cursor resolution -------------------------------------------------------------


class _CursorRequest:
    def __init__(self, headers=None, query=None):
        self.headers = headers or {}
        self.query_params = query or {}


def test_initial_cursor_prefers_last_event_id_over_since_seq():
    req = _CursorRequest(headers={"last-event-id": "7"}, query={"since_seq": "2"})
    assert ros._initial_cursor(req) == 7


def test_initial_cursor_falls_back_to_since_seq():
    req = _CursorRequest(query={"since_seq": "5"})
    assert ros._initial_cursor(req) == 5


def test_initial_cursor_defaults_to_zero():
    assert ros._initial_cursor(_CursorRequest()) == 0


def test_initial_cursor_ignores_malformed_header():
    req = _CursorRequest(headers={"last-event-id": "not-a-number"}, query={"since_seq": "3"})
    assert ros._initial_cursor(req) == 3


# --- routes: list_rooms + auth gate -------------------------------------------------


def test_list_rooms_route_returns_seeded_rooms(tmp_path):
    _seed(tmp_path, 1)
    from my_crew.server.app import create_app

    with TestClient(create_app()) as client:
        r = client.get("/api/office/rooms")
        assert r.status_code == 200
        assert r.json() == {"rooms": ["t1"]}


@pytest.fixture
def auth_env(monkeypatch):
    from my_crew.server import auth

    monkeypatch.setenv("WEB_AUTH_USERNAME", "ceo")
    monkeypatch.setenv("WEB_AUTH_PASSWORD_HASH", auth.hash_password("s3cret"))
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    auth._login_attempts.clear()


def test_office_routes_require_auth_when_enabled(auth_env):
    from my_crew.server.app import create_app

    with TestClient(create_app()) as client:
        assert client.get("/api/office/rooms").status_code == 401
        assert client.get("/api/office/rooms/t1/stream").status_code == 401


def test_stream_route_wire_bytes_carry_no_event_line(tmp_path):
    """Wire-contract pin against the REAL `sse_starlette` byte encoder (not a live HTTP
    stream): `_tail` is an infinite poll loop by design (see module docstring, and
    `test_tail_frames_carry_no_event_key` above for the direct-drain pin) — attaching a
    real `TestClient` HTTP stream to it has no clean disconnect signal to end on and
    hangs the run. Instead this builds the EXACT same `ServerSentEvent` `EventSourceResponse`
    constructs from one of `_tail`'s own yielded dicts and encodes it through the real
    library path, asserting the on-wire bytes have no `event:` line — only `id:`/`data:`
    — so a browser `EventSource`'s default `onmessage` handler receives it. A regression
    back to a named `event: <kind>` frame would pass every other test (they mock the
    hook or drain `_tail` in Python) but silently break the frontend in production."""
    from sse_starlette.sse import ensure_bytes

    _seed(tmp_path, 1)
    request = _FakeRequest(max_polls=1)
    frames = asyncio.run(_run_tail_frames("t1", 0, request))
    assert len(frames) == 1

    raw = ensure_bytes(frames[0], None)
    text = raw.decode("utf-8")
    lines = [ln for ln in text.split("\r\n") if ln]
    assert not any(ln.startswith("event:") for ln in lines)
    assert any(ln.startswith("id:") for ln in lines)
    data_lines = [ln for ln in lines if ln.startswith("data:")]
    assert data_lines
    payload = json.loads(data_lines[0][len("data:"):].strip())
    assert payload["kind"] == "ceo"


async def _run_tail_frames(room_id: str, since_seq: int, request) -> list[dict]:
    return [frame async for frame in ros._tail(room_id, since_seq, request)]
