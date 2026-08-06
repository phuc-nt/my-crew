"""A tick must start every due worker before waiting on any of them.

The defect this locks down: `run_tick` spawned a worker and immediately `proc.wait()`ed
it before moving to the next entry, so a tick cost the SUM of its workers' runtimes.
Measured in production: 65s median / 108s max per tick against a 60s interval. Because
the fairness rotation (`test_service_tick_fairness.py`) advances only ONE registry slot
per tick, an overrunning tick also slows fairness proportionally — `pong`'s inbox,
scheduled every minute, actually ran 6 times while the coordinator ran 338, with gaps of
28 to 144 minutes. The CEO's Telegram messages were queueing behind background work.

Spawning is cheap; waiting is what must not be serialized. These tests assert the
overlap directly, since a wall-clock assertion would be flaky.
"""

from __future__ import annotations

from datetime import datetime

from my_crew.runtime import service
from my_crew.runtime.registry import RegistryEntry
from tests.test_service import _patch, _profile

_8AM = datetime(2026, 6, 24, 8, 0, 0)
_YESTERDAY = datetime(2026, 6, 23, 9, 0, 0)


class _TracingProc:
    """Records the spawn/wait interleaving into a shared event log."""

    def __init__(self, agent_id: str, events: list, *, exit_code: int = 0):
        self._agent_id = agent_id
        self._events = events
        self._exit_code = exit_code
        self.killed = False

    def wait(self, timeout=None):
        self._events.append(("wait", self._agent_id))
        return self._exit_code

    def kill(self):
        self.killed = True


def _tracing_spawn(events: list):
    def _spawn(argv):
        agent_id = argv[argv.index("--agent-id") + 1]
        events.append(("spawn", agent_id))
        return _TracingProc(agent_id, events)

    return _spawn


def _three_agents_due(monkeypatch, *, cap=4):
    entries = [RegistryEntry(f"ag{i}", True) for i in range(3)]
    profiles = {f"ag{i}": _profile() for i in range(3)}
    _patch(monkeypatch, entries, profiles)
    svc = service.Service(cap=cap)
    svc._last_fire = {(f"ag{i}", "daily"): _YESTERDAY for i in range(3)}
    svc._seeded = True
    return svc


def test_all_due_workers_start_before_any_is_waited_on(monkeypatch):
    """The whole point: three due workers means three spawns, THEN three waits — not
    spawn/wait/spawn/wait. Under the old shape every wait immediately followed its own
    spawn, so the tick's cost was additive."""
    events: list = []
    _three_agents_due(monkeypatch).run_tick(_8AM, spawn=_tracing_spawn(events))

    phases = [kind for kind, _ in events]
    assert phases == ["spawn"] * 3 + ["wait"] * 3, (
        f"tick serialized spawn and wait: {events}"
    )


def test_outcomes_still_arrive_in_spawn_order(monkeypatch):
    """Draining concurrently must not reorder results — callers and the fairness tests
    read `outcomes` positionally."""
    events: list = []
    out = _three_agents_due(monkeypatch).run_tick(_8AM, spawn=_tracing_spawn(events))

    spawn_order = [aid for kind, aid in events if kind == "spawn"]
    assert [o["agent_id"] for o in out] == spawn_order


def test_a_hung_worker_does_not_swallow_a_later_worker_outcome(monkeypatch):
    """A worker that times out is killed and reported, and every worker spawned after it
    still gets collected — the drain must not abort on the first timeout."""
    import subprocess

    events: list = []

    def _spawn(argv):
        agent_id = argv[argv.index("--agent-id") + 1]
        events.append(("spawn", agent_id))
        proc = _TracingProc(agent_id, events)
        if agent_id == "ag0":  # the first one hangs

            def _hang(timeout=None):
                raise subprocess.TimeoutExpired(cmd="worker", timeout=timeout)

            proc.wait = _hang
        return proc

    out = _three_agents_due(monkeypatch).run_tick(_8AM, spawn=_spawn)

    assert [o["agent_id"] for o in out] == ["ag0", "ag1", "ag2"]
    assert out[0]["status"] == "timeout"
    assert [o["status"] for o in out[1:]] == ["ran", "ran"]


def test_the_cap_still_bounds_how_many_run_at_once(monkeypatch):
    """Overlapping the waits must not become a way to exceed the load bound."""
    events: list = []
    _three_agents_due(monkeypatch, cap=2).run_tick(_8AM, spawn=_tracing_spawn(events))

    assert len([e for e in events if e[0] == "spawn"]) == 2
