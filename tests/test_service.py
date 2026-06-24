"""Slice 3: coordinating service run_tick — fake spawn + injected now, no real process."""

from __future__ import annotations

import subprocess
from datetime import datetime

from src.runtime import service
from src.runtime.registry import RegistryEntry

_8AM = datetime(2026, 6, 24, 8, 0, 0)
_YESTERDAY = datetime(2026, 6, 23, 9, 0, 0)


class _FakeProc:
    """A fake Popen: configurable exit code or a hang (raises TimeoutExpired on wait)."""

    def __init__(self, exit_code=0, hang=False):
        self._exit_code = exit_code
        self._hang = hang
        self.killed = False

    def wait(self, timeout=None):
        if self._hang:
            raise subprocess.TimeoutExpired(cmd="worker", timeout=timeout)
        return self._exit_code

    def kill(self):
        self.killed = True


def _fake_spawn(record, *, exit_code=0, hang=False):
    def _spawn(argv):
        record.append(argv)
        return _FakeProc(exit_code=exit_code, hang=hang)

    return _spawn


def _patch(monkeypatch, entries, profiles):
    """Stub load_registry + load_profile so run_tick is fully offline."""
    monkeypatch.setattr(service, "load_registry", lambda: tuple(entries))

    def _load(agent_id):
        return profiles[agent_id]

    monkeypatch.setattr(service, "load_profile", _load)


def _profile(enabled=True, schedule=None, reports=("daily",)):
    sched = schedule if schedule is not None else {"daily": "0 8 * * *"}
    return type("LP", (), {"enabled": enabled, "schedule": sched, "reports": reports})()


def test_two_enabled_agents_both_spawn_exact_argv(monkeypatch):
    entries = [RegistryEntry("acme-web", True), RegistryEntry("beta-app", True)]
    profiles = {"acme-web": _profile(), "beta-app": _profile()}
    _patch(monkeypatch, entries, profiles)
    record = []
    svc = service.Service()
    svc._last_fire = {("acme-web", "daily"): _YESTERDAY, ("beta-app", "daily"): _YESTERDAY}
    svc._seeded = True  # skip auto-seed so we control last_fire
    svc.run_tick(_8AM, spawn=_fake_spawn(record))
    assert [a[a.index("--agent-id") + 1] for a in record] == ["acme-web", "beta-app"]
    assert record[0] == [
        service.sys.executable, "-m", "src.runtime.worker",
        "--agent-id", "acme-web", "--report", "daily", "--audience", "internal",
    ]


def test_registry_disabled_agent_skipped(monkeypatch):
    entries = [RegistryEntry("on", True), RegistryEntry("off", False)]
    profiles = {"on": _profile(), "off": _profile()}
    _patch(monkeypatch, entries, profiles)
    record = []
    svc = service.Service()
    svc._last_fire = {("on", "daily"): _YESTERDAY, ("off", "daily"): _YESTERDAY}
    svc._seeded = True
    svc.run_tick(_8AM, spawn=_fake_spawn(record))
    assert [a[a.index("--agent-id") + 1] for a in record] == ["on"]  # "off" never spawned


def test_profile_disabled_agent_skipped(monkeypatch):
    entries = [RegistryEntry("a", True), RegistryEntry("b", True)]
    profiles = {"a": _profile(enabled=True), "b": _profile(enabled=False)}
    _patch(monkeypatch, entries, profiles)
    record = []
    svc = service.Service()
    svc._last_fire = {("a", "daily"): _YESTERDAY, ("b", "daily"): _YESTERDAY}
    svc._seeded = True
    svc.run_tick(_8AM, spawn=_fake_spawn(record))
    assert [a[a.index("--agent-id") + 1] for a in record] == ["a"]


def test_concurrency_cap_defers_overflow(monkeypatch):
    entries = [RegistryEntry(f"ag{i}", True) for i in range(5)]
    profiles = {f"ag{i}": _profile() for i in range(5)}
    _patch(monkeypatch, entries, profiles)
    svc = service.Service(cap=4)
    svc._last_fire = {(f"ag{i}", "daily"): _YESTERDAY for i in range(5)}
    svc._seeded = True
    record = []
    out = svc.run_tick(_8AM, spawn=_fake_spawn(record))
    assert len(record) == 4 and len(out) == 4  # only 4 of 5 spawn this tick
    # the 5th (ag4) was deferred: its last_fire was NOT advanced → fires next tick.
    record2 = []
    svc.run_tick(_8AM, spawn=_fake_spawn(record2))
    assert [a[a.index("--agent-id") + 1] for a in record2] == ["ag4"]


def test_timeout_kills_and_records_status(monkeypatch):
    entries = [RegistryEntry("a", True)]
    profiles = {"a": _profile()}
    _patch(monkeypatch, entries, profiles)
    svc = service.Service(timeout=1)
    svc._last_fire = {("a", "daily"): _YESTERDAY}
    svc._seeded = True
    record = []
    out = svc.run_tick(_8AM, spawn=_fake_spawn(record, hang=True))
    assert out[0]["status"] == "timeout" and out[0]["exit_code"] is None


def test_worker_crash_no_same_tick_respawn(monkeypatch):
    entries = [RegistryEntry("a", True)]
    profiles = {"a": _profile()}
    _patch(monkeypatch, entries, profiles)
    svc = service.Service()
    svc._last_fire = {("a", "daily"): _YESTERDAY}
    svc._seeded = True
    record = []
    out = svc.run_tick(_8AM, spawn=_fake_spawn(record, exit_code=1))
    assert len(record) == 1  # spawned once; crash does NOT trigger a same-tick re-spawn
    assert out[0]["exit_code"] == 1


def test_once_runs_one_tick(monkeypatch):
    entries = [RegistryEntry("a", True)]
    profiles = {"a": _profile(schedule={})}  # no schedule ⇒ nothing fires
    _patch(monkeypatch, entries, profiles)
    ticks = {"n": 0}
    real_run_tick = service.Service.run_tick

    def _counting(self, now, **kw):
        ticks["n"] += 1
        return real_run_tick(self, now, **kw)

    monkeypatch.setattr(service.Service, "run_tick", _counting)
    rc = service.main(["--once"])
    assert rc == 0 and ticks["n"] == 1  # exactly one tick, no loop
