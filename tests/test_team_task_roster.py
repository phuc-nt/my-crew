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


# --- capability tuple (context-crew role) ------------------------------------------


def _profile(*, kind="native", web=False, gws=False, gws_enabled=True, model="fleet-m"):
    return SimpleNamespace(
        domain="office", web_search=web, gws_context=gws,
        agent_runtime=SimpleNamespace(kind=kind),
        config=SimpleNamespace(gws_enabled=gws_enabled, openrouter_model=model),
    )


def test_capability_is_derived_from_tools_and_model_not_persona(monkeypatch):
    profiles = {
        "a": _profile(kind="deep_agent", web=True, model="m1"),
        "b": _profile(kind="deep_agent", web=True, model="m1"),
        "c": _profile(kind="deep_agent", web=True, model="m2"),
        "d": _profile(gws=True, gws_enabled=False),
    }
    monkeypatch.setattr(
        loader_mod, "load_profile", lambda agent_id, *, data_dir: profiles[agent_id],
    )
    monkeypatch.delenv("RUNTIME_FORCE_NATIVE", raising=False)

    caps = roster_mod.capability_map(["a", "b", "c", "d"])
    assert caps["a"] == caps["b"]
    assert caps["a"] == roster_mod.Capability(tier="deep_agent", web=True, mail=False, model="m1")
    assert caps["a"] != caps["c"]  # a different model is a different role
    assert caps["d"].mail is False  # gws_context alone is not mail access


def test_a_tools_tier_agent_and_a_native_agent_are_different_roles(monkeypatch):
    """Same web flag, same model, different runtime kind ⇒ different tuple. Measured live:
    with the tier missing from the tuple, the analyst's `create_agent` research step folded
    into the native writer's step, so no step ever reached ToolCallingRuntime."""
    profiles = {
        "analyst": _profile(kind="create_agent", web=False, model="m1"),
        "writer": _profile(kind="native", web=False, model="m1"),
    }
    monkeypatch.setattr(
        loader_mod, "load_profile", lambda agent_id, *, data_dir: profiles[agent_id],
    )
    monkeypatch.delenv("RUNTIME_FORCE_NATIVE", raising=False)

    caps = roster_mod.capability_map(["analyst", "writer"])
    assert caps["analyst"].tier == "create_agent"
    assert caps["writer"].tier == "native"
    assert caps["analyst"] != caps["writer"]


def test_unknown_profile_has_no_capability(monkeypatch):
    def _missing(agent_id, *, data_dir):
        raise FileNotFoundError(agent_id)

    monkeypatch.setattr(loader_mod, "load_profile", _missing)
    assert roster_mod.agent_capability("ghost") is None


# --- planning roster: the planner sees the tool boundary, not only the domain ---------


def test_capability_hint_names_what_the_tuple_lets_the_agent_do():
    """Native ⇒ says it has no tools; tools tiers ⇒ history/integrations; deep adds shell;
    web and mail are appended only when set. Unknown capability claims nothing."""
    hint = roster_mod.capability_hint
    assert "không có công cụ" in hint(roster_mod.Capability(tier="native"))
    assert "tra lịch sử làm việc nội bộ" in hint(roster_mod.Capability(tier="create_agent"))
    assert "shell" not in hint(roster_mod.Capability(tier="create_agent"))
    assert "shell" in hint(roster_mod.Capability(tier="deep_agent"))
    assert "web" in hint(roster_mod.Capability(tier="native", web=True))
    assert "thư" in hint(roster_mod.Capability(tier="native", mail=True))
    assert hint(None) == ""


def test_planning_roster_keeps_ids_and_extends_domains_with_the_hint(monkeypatch):
    """Measured live: a "tra lịch sử làm việc" step landed on the native secretary one
    run in four because the decomposer could not see that only the analyst has the
    history tool. Ids stay identical to `assignable_staff` (validators read those)."""
    monkeypatch.setattr(
        roster_mod, "assignable_staff", lambda: [("analyst", "research"), ("writer", "pm")],
    )
    monkeypatch.setattr(
        roster_mod, "capability_map",
        lambda ids: {
            "analyst": roster_mod.Capability(tier="create_agent", web=True),
            "writer": None,
        },
    )

    roster = roster_mod.planning_roster()

    assert [a for a, _ in roster] == ["analyst", "writer"]
    assert roster[0][1].startswith("research — ")
    assert "tra lịch sử làm việc nội bộ" in roster[0][1]
    assert "web" in roster[0][1]
    assert roster[1] == ("writer", "pm")  # nothing known ⇒ nothing claimed
