"""The per-tick spawn cap must bound HOW MANY workers start, not WHICH agents ever get
to start. Traversing the registry from a fixed index turns the cap into a permanent
priority order — UAT-observed: one agent's `inbox` kind deferred 488 consecutive ticks
because the four agents ahead of it refilled the cap every time.
"""

from __future__ import annotations

from datetime import datetime

from my_crew.runtime import service
from my_crew.runtime.registry import RegistryEntry
from tests.test_service import _fake_spawn, _patch, _profile

_8AM = datetime(2026, 6, 24, 8, 0, 0)
_YESTERDAY = datetime(2026, 6, 23, 9, 0, 0)


def _six_agents_all_due(monkeypatch):
    entries = [RegistryEntry(f"ag{i}", True) for i in range(6)]
    profiles = {f"ag{i}": _profile(schedule={"daily": "* * * * *"}) for i in range(6)}
    _patch(monkeypatch, entries, profiles)
    svc = service.Service(cap=4)
    svc._last_fire = {(f"ag{i}", "daily"): _YESTERDAY for i in range(6)}
    svc._seeded = True
    return svc


def test_every_agent_runs_within_a_few_ticks(monkeypatch):
    """Six agents, cap 4, everyone due every minute. Before rotation, ag4/ag5 never ran."""
    svc = _six_agents_all_due(monkeypatch)
    ran: set[str] = set()
    now = _8AM
    for minute in range(3):
        now = _8AM.replace(minute=minute)
        record: list = []
        svc.run_tick(now, spawn=_fake_spawn(record))
        ran.update(argv[argv.index("--agent-id") + 1] for argv in record)
    assert ran == {f"ag{i}" for i in range(6)}


def test_rotation_does_not_lift_the_cap(monkeypatch):
    """Fairness must not come at the cost of the load bound the cap exists to enforce."""
    svc = _six_agents_all_due(monkeypatch)
    record: list = []
    svc.run_tick(_8AM, spawn=_fake_spawn(record))
    assert len(record) == 4


def test_rotation_advances_the_start_agent(monkeypatch):
    """Tick N+1 must not begin at the same agent tick N did."""
    svc = _six_agents_all_due(monkeypatch)
    first: list = []
    svc.run_tick(_8AM, spawn=_fake_spawn(first))
    second: list = []
    svc.run_tick(_8AM.replace(minute=1), spawn=_fake_spawn(second))
    assert first[0][first[0].index("--agent-id") + 1] != second[0][
        second[0].index("--agent-id") + 1
    ]


def test_milestone_mirror_is_cap_exempt(monkeypatch):
    """A milestone is by definition the moment the CEO needs to know. The mirror body is
    one SQLite read plus one HTTP send — no LLM — so the cap has no load reason to hold
    it, and holding it defeats the kind's only purpose."""
    entries = [RegistryEntry(f"ag{i}", True) for i in range(4)] + [RegistryEntry("admin", True)]
    profiles = {f"ag{i}": _profile() for i in range(4)}
    profiles["admin"] = _profile(schedule={"milestone-mirror": "* * * * *"},
                                 reports=("milestone-mirror",))
    _patch(monkeypatch, entries, profiles)
    svc = service.Service(cap=4)
    svc._last_fire = {(f"ag{i}", "daily"): _YESTERDAY for i in range(4)}
    svc._last_fire[("admin", "milestone-mirror")] = _YESTERDAY
    svc._seeded = True
    record: list = []
    out = svc.run_tick(_8AM, spawn=_fake_spawn(record))
    fired = [(o["agent_id"], o["kind"]) for o in out]
    assert ("admin", "milestone-mirror") in fired
    assert len([k for k in fired if k[1] == "daily"]) == 4  # cap still bounds the rest


def test_team_tick_is_cap_exempt(monkeypatch):
    """team-tick is the coordinator's control loop — the thing that notices a finished
    or failed step and issues the next decision. There is exactly one coordinator, so
    exempting it adds at most one worker per tick; holding it behind a full cap starves
    the whole team pipeline (observed: a failed step waited >3h for its ruling)."""
    entries = [RegistryEntry(f"ag{i}", True) for i in range(4)] + [
        RegistryEntry("coordinator", True)
    ]
    profiles = {f"ag{i}": _profile() for i in range(4)}
    profiles["coordinator"] = _profile(schedule={"team-tick": "* * * * *"},
                                       reports=("team-tick",))
    _patch(monkeypatch, entries, profiles)
    svc = service.Service(cap=4)
    svc._last_fire = {(f"ag{i}", "daily"): _YESTERDAY for i in range(4)}
    svc._last_fire[("coordinator", "team-tick")] = _YESTERDAY
    svc._seeded = True
    record: list = []
    out = svc.run_tick(_8AM, spawn=_fake_spawn(record))
    fired = [(o["agent_id"], o["kind"]) for o in out]
    assert ("coordinator", "team-tick") in fired
    assert len([k for k in fired if k[1] == "daily"]) == 4  # cap still bounds the rest
