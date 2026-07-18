"""`team_task_roster.assignable_staff`/`is_assignable` (v12 MAJOR-4): the single
source of truth both the decompose-validation gate and the dispatch-time re-check use
for "who can be assigned a team-task step" — must exclude the coordinator and the
admin agent even though both are enabled registry agents.
"""

from __future__ import annotations

from types import SimpleNamespace

import my_crew.agent.team_task_roster as roster_mod
import my_crew.profile.loader as loader_mod
import my_crew.runtime.company as company_mod
import my_crew.runtime.registry as registry_mod


def _entry(agent_id: str, *, enabled: bool = True):
    return SimpleNamespace(id=agent_id, enabled=enabled)


def _wire(monkeypatch, *, entries, coordinator_id, domains: dict[str, str]):
    monkeypatch.setattr(registry_mod, "load_registry", lambda: tuple(entries))
    monkeypatch.setattr(
        company_mod, "load_company",
        lambda: SimpleNamespace(name="", coordinator_id=coordinator_id, team_task_cap_usd=2.0),
    )

    def _load_profile(agent_id, *, data_dir):
        if agent_id not in domains:
            raise FileNotFoundError(agent_id)
        return SimpleNamespace(domain=domains[agent_id])

    monkeypatch.setattr(loader_mod, "load_profile", _load_profile)


def test_assignable_staff_excludes_coordinator(monkeypatch):
    _wire(
        monkeypatch,
        entries=[_entry("coord-1"), _entry("agent-a")],
        coordinator_id="coord-1",
        domains={"coord-1": "coordinator", "agent-a": "pm"},
    )
    roster = roster_mod.assignable_staff()
    assert roster == [("agent-a", "pm")]


def test_assignable_staff_excludes_admin_domain(monkeypatch):
    _wire(
        monkeypatch,
        entries=[_entry("admin-1"), _entry("agent-a")],
        coordinator_id=None,
        domains={"admin-1": "admin", "agent-a": "pm"},
    )
    roster = roster_mod.assignable_staff()
    assert roster == [("agent-a", "pm")]


def test_assignable_staff_excludes_disabled_registry_entries(monkeypatch):
    _wire(
        monkeypatch,
        entries=[_entry("agent-a", enabled=False), _entry("agent-b")],
        coordinator_id=None,
        domains={"agent-a": "pm", "agent-b": "pm"},
    )
    roster = roster_mod.assignable_staff()
    assert roster == [("agent-b", "pm")]


def test_assignable_staff_skips_unloadable_profile(monkeypatch):
    _wire(
        monkeypatch,
        entries=[_entry("ghost"), _entry("agent-a")],
        coordinator_id=None,
        domains={"agent-a": "pm"},  # "ghost" not in domains -> load_profile raises
    )
    roster = roster_mod.assignable_staff()
    assert roster == [("agent-a", "pm")]


def test_is_assignable_true_for_normal_staff_false_for_coordinator_and_admin(monkeypatch):
    _wire(
        monkeypatch,
        entries=[_entry("coord-1"), _entry("admin-1"), _entry("agent-a")],
        coordinator_id="coord-1",
        domains={"coord-1": "coordinator", "admin-1": "admin", "agent-a": "pm"},
    )
    assert roster_mod.is_assignable("agent-a") is True
    assert roster_mod.is_assignable("coord-1") is False
    assert roster_mod.is_assignable("admin-1") is False
    assert roster_mod.is_assignable("no-such-agent") is False
