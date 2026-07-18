"""`ops_assign_team_task._escalation_routable` + its wiring into `preview_assign_team_task`
(v12 MAJOR-6): a team task must never be draftable if its coordinator's Telegram
escalation path is unroutable — the ticker's `escalate` collaborator would silently
fail (see `team_tick_collaborators.make_escalate`) and the task would have no safety
net at all for a stuck/failed step.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import my_crew.agent.ops_assign_team_task as mod
import my_crew.profile.loader as loader_mod
import my_crew.runtime.company as company_mod
import my_crew.runtime.registry as registry_mod
from my_crew.runtime.registry import RegistryEntry


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    """Every test in this module writes through the shared cross-agent root (store,
    artifacts, office-room appends) — pin it to tmp_path so no test can touch the
    real install's .data (the office room is a real user-visible surface)."""
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)

def _company(coordinator_id):
    return SimpleNamespace(name="", coordinator_id=coordinator_id, team_task_cap_usd=2.0)


def _profile_with_telegram(*, ops_operator_id: str, chat_ids: tuple[str, ...], domain: str = "pm"):
    telegram = SimpleNamespace(
        bot_token_env="X", chat_ids=chat_ids, poll_minutes=5, ops_operator_id=ops_operator_id
    )
    return SimpleNamespace(domain=domain, config=SimpleNamespace(telegram=telegram))


def _profile_no_telegram(*, domain: str = "pm"):
    return SimpleNamespace(domain=domain, config=SimpleNamespace(telegram=None))


# --- _escalation_routable -----------------------------------------------------------


def test_escalation_routable_true_when_operator_in_chat_ids(monkeypatch):
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))
    monkeypatch.setattr(
        loader_mod, "load_profile",
        lambda agent_id, **kw: _profile_with_telegram(
            ops_operator_id="op-1", chat_ids=("op-1", "group-2")
        ),
    )
    assert mod._escalation_routable() is True


def test_escalation_routable_false_when_no_coordinator_configured(monkeypatch):
    monkeypatch.setattr(company_mod, "load_company", lambda: _company(None))
    assert mod._escalation_routable() is False


def test_escalation_routable_false_when_coordinator_profile_unloadable(monkeypatch):
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))

    def _raise(agent_id, **kw):
        raise FileNotFoundError(agent_id)

    monkeypatch.setattr(loader_mod, "load_profile", _raise)
    assert mod._escalation_routable() is False


def test_escalation_routable_false_when_no_telegram_configured(monkeypatch):
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))
    monkeypatch.setattr(loader_mod, "load_profile", lambda agent_id, **kw: _profile_no_telegram())
    assert mod._escalation_routable() is False


def test_escalation_routable_false_when_no_operator_id_set(monkeypatch):
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))
    monkeypatch.setattr(
        loader_mod, "load_profile",
        lambda agent_id, **kw: _profile_with_telegram(ops_operator_id="", chat_ids=("g1",)),
    )
    assert mod._escalation_routable() is False


def test_escalation_routable_false_when_operator_not_in_chat_ids(monkeypatch):
    """The real bug this finding targets: an operator id is set but NOT allowlisted —
    `telegram_write.send_telegram_message` would refuse every escalation send."""
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))
    monkeypatch.setattr(
        loader_mod, "load_profile",
        lambda agent_id, **kw: _profile_with_telegram(
            ops_operator_id="op-1", chat_ids=("some-other-chat",)
        ),
    )
    assert mod._escalation_routable() is False


def test_escalation_routable_true_via_admin_mirror_when_coordinator_has_no_binding_of_its_own(
    monkeypatch,
):
    """The mirror path (v12 final-review escalation-reachability redesign): the
    coordinator itself has no Telegram binding, but an ENABLED admin-domain agent does
    — every escalation reaches it via the office-room `milestone` mirror
    (`milestone_mirror_runner`), so the task is still routable."""
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))
    monkeypatch.setattr(
        registry_mod, "load_registry", lambda: (RegistryEntry(id="admin", enabled=True),),
    )

    def _load_profile(agent_id, **kw):
        if agent_id == "coord-1":
            return _profile_no_telegram(domain="pm")
        if agent_id == "admin":
            return _profile_with_telegram(
                ops_operator_id="op-1", chat_ids=("op-1",), domain="admin",
            )
        raise FileNotFoundError(agent_id)

    monkeypatch.setattr(loader_mod, "load_profile", _load_profile)
    assert mod._escalation_routable() is True


def test_escalation_routable_false_when_neither_coordinator_nor_any_admin_agent_has_a_route(
    monkeypatch,
):
    """Neither the fast path (coordinator's own binding) nor the mirror path (an
    enabled admin-domain agent's binding) works — genuinely unroutable."""
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))
    monkeypatch.setattr(
        registry_mod, "load_registry", lambda: (RegistryEntry(id="admin", enabled=True),),
    )

    def _load_profile(agent_id, **kw):
        if agent_id == "coord-1":
            return _profile_no_telegram(domain="pm")
        if agent_id == "admin":
            return _profile_no_telegram(domain="admin")
        raise FileNotFoundError(agent_id)

    monkeypatch.setattr(loader_mod, "load_profile", _load_profile)
    assert mod._escalation_routable() is False


def test_escalation_routable_ignores_a_disabled_admin_agents_route(monkeypatch):
    """A disabled admin agent's binding does not count — `milestone_mirror_runner`
    only runs for an ENABLED admin agent's scheduled ops-tick."""
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))
    monkeypatch.setattr(
        registry_mod, "load_registry", lambda: (RegistryEntry(id="admin", enabled=False),),
    )

    def _load_profile(agent_id, **kw):
        if agent_id == "coord-1":
            return _profile_no_telegram(domain="pm")
        if agent_id == "admin":
            return _profile_with_telegram(
                ops_operator_id="op-1", chat_ids=("op-1",), domain="admin",
            )
        raise FileNotFoundError(agent_id)

    monkeypatch.setattr(loader_mod, "load_profile", _load_profile)
    assert mod._escalation_routable() is False


def test_escalation_routable_ignores_a_non_admin_agents_route(monkeypatch):
    """An enabled agent with a working Telegram binding but domain != "admin" does not
    provide the mirror path — `milestone_mirror_runner`'s ops-tick is scheduled only
    for admin-domain agents (`my_crew.runtime.service._effective_schedule`)."""
    monkeypatch.setattr(company_mod, "load_company", lambda: _company("coord-1"))
    monkeypatch.setattr(
        registry_mod, "load_registry", lambda: (RegistryEntry(id="sales", enabled=True),),
    )

    def _load_profile(agent_id, **kw):
        if agent_id == "coord-1":
            return _profile_no_telegram(domain="pm")
        if agent_id == "sales":
            return _profile_with_telegram(
                ops_operator_id="op-1", chat_ids=("op-1",), domain="pm",
            )
        raise FileNotFoundError(agent_id)

    monkeypatch.setattr(loader_mod, "load_profile", _load_profile)
    assert mod._escalation_routable() is False


# --- preview_assign_team_task wiring -------------------------------------------------


def test_preview_assign_team_task_blocks_with_vietnamese_error_when_unroutable(monkeypatch):
    monkeypatch.setattr(mod, "_escalation_routable", lambda: False)
    with pytest.raises(ValueError, match="báo cáo sự cố"):
        mod.preview_assign_team_task({"brief": "chuẩn bị demo"})


def test_preview_assign_team_task_proceeds_past_escalation_gate_when_routable(monkeypatch):
    """Escalation check passes -> the function proceeds to the NEXT gate (staff
    roster), proving the escalation check does not block a routable setup. We stop the
    test right after that by making the staff roster empty (a distinct, well-understood
    failure) rather than standing up the full LLM/store stack."""
    monkeypatch.setattr(mod, "_escalation_routable", lambda: True)
    monkeypatch.setattr(mod, "_staff_roster", lambda: [])
    with pytest.raises(ValueError, match="chưa có nhân sự"):
        mod.preview_assign_team_task({"brief": "chuẩn bị demo"})
