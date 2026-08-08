"""v74 phase 2: poke-driven early team-tick.

The decision (`Service.poke_pending` — watermark debounce) and the action
(`Service.run_poked_team_tick` — exact coordinator argv) are unit-tested here;
`_sleep_watching_pokes` is the thin timing wrapper composing them, untested like
`run_forever` itself.
"""

from __future__ import annotations

from my_crew.runtime import service, tick_poke


class _FakeProc:
    def wait(self, timeout=None):
        return 0

    def kill(self):  # pragma: no cover — never hit with exit 0
        pass


def _set_poke_mtime(monkeypatch, value):
    monkeypatch.setattr(tick_poke, "poke_mtime", lambda: value)


def test_first_look_adopts_stale_poke_as_handled(monkeypatch):
    """A poke left on disk by a previous daemon run must not fire at startup."""
    svc = service.Service()
    _set_poke_mtime(monkeypatch, 100.0)
    assert svc.poke_pending() is False  # first look: adopt, never fire
    assert svc.poke_pending() is False  # unchanged mtime stays handled


def test_fresh_poke_fires_once_then_debounces(monkeypatch):
    svc = service.Service()
    _set_poke_mtime(monkeypatch, 100.0)
    assert svc.poke_pending() is False  # seeding look
    _set_poke_mtime(monkeypatch, 200.0)
    assert svc.poke_pending() is True  # a worker finished → one early tick
    assert svc.poke_pending() is False  # burst inside the window: already handled
    _set_poke_mtime(monkeypatch, 300.0)
    assert svc.poke_pending() is True  # a later finish is a new signal


def test_no_poke_file_never_fires(monkeypatch):
    svc = service.Service()
    _set_poke_mtime(monkeypatch, None)
    assert svc.poke_pending() is False
    assert svc.poke_pending() is False


def test_run_poked_team_tick_spawns_exact_coordinator_argv(monkeypatch):
    import my_crew.runtime.company as company_mod

    monkeypatch.setattr(
        company_mod, "load_company",
        lambda: type("C", (), {"coordinator_id": "coord-x"})(),
    )
    monkeypatch.setattr(service, "_last_run_event", lambda agent_id: None)
    record = []

    def _spawn(argv):
        record.append(argv)
        return _FakeProc()

    svc = service.Service()
    outcome = svc.run_poked_team_tick(spawn=_spawn)
    assert record == [[
        service.sys.executable, "-m", "my_crew.runtime.worker",
        "--agent-id", "coord-x", "--report", "team-tick", "--audience", "internal",
    ]]
    assert outcome["status"] == "ran"
    assert outcome["exit_code"] == 0


def test_run_poked_team_tick_without_coordinator_is_noop(monkeypatch):
    import my_crew.runtime.company as company_mod

    monkeypatch.setattr(
        company_mod, "load_company",
        lambda: type("C", (), {"coordinator_id": ""})(),
    )
    record = []

    def _spawn(argv):  # pragma: no cover — must not be reached
        record.append(argv)
        return _FakeProc()

    svc = service.Service()
    assert svc.run_poked_team_tick(spawn=_spawn) is None
    assert record == []
