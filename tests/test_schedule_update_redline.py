"""v31 P2 redline: the native `schedule_update` type — Lớp A hard categories hold at
EVERY door (chat enqueue, direct execute, approve-reentry) in BOTH trust modes; the
write handler re-enforces floor/kind/caps itself; identity is a closure, never payload.
"""

from __future__ import annotations

import pytest
import yaml

from my_crew.actions.action_gateway import (
    AUTONOMOUS_RATIONALE,
    ActionGateway,
    HardBlockedError,
)
from my_crew.actions.hard_block import BlockCategory, classify, cron_floor_error, needs_interrupt
from my_crew.actions.schedule_write import make_schedule_update_handler
from my_crew.audit.audit_log import AuditLog
from my_crew.config.config_builders import build_settings_from_dict

# A fake OpenRouter-shaped key, assembled at runtime so repo scanners don't flag the
# test source itself; `contains_secret` sees the joined value exactly the same.
_FAKE_KEY = "OPENROUTER_API_KEY=" + "sk" + "-or-v1-" + "abcdef1234567890abcdef"


def _settings(tmp_path, trust_mode):
    return build_settings_from_dict({
        "data_dir": tmp_path / "data", "dry_run": False, "monthly_budget_usd": 50.0,
        "trust_mode": trust_mode,
    })


def _action(schedule=None, **extra):
    return {"type": "schedule_update",
            "schedule": schedule if schedule is not None else {"daily": "0 8 * * *"},
            **extra}


# --- classify: hard categories (never NOT_ALLOWLISTED) ---


def test_valid_update_passes_lop_a():
    assert classify(_action()).blocked is False


@pytest.mark.parametrize("schedule", [None, {}, "0 8 * * *", {"daily": "not a cron"},
                                      {"": "0 8 * * *"}, {"daily": "* * * * *"},
                                      {"daily": "*/2 * * * *"}])
def test_structural_and_floor_denies_are_hard_categories(schedule):
    action = {"type": "schedule_update"}
    if schedule is not None:
        action["schedule"] = schedule
    verdict = classify(action)
    assert verdict.blocked
    # HARD category — a NOT_ALLOWLISTED verdict would be bypassed by the autonomous
    # re-entry (approved=True) and by human approve; these must hold at every door.
    assert verdict.category == BlockCategory.SECURITY


def test_too_many_entries_denied():
    schedule = {f"kind{i}": "0 8 * * *" for i in range(7)}
    verdict = classify(_action(schedule))
    assert verdict.blocked and verdict.category == BlockCategory.SECURITY


def test_credential_in_payload_denied():
    verdict = classify(_action({"daily": "0 8 * * *"}, note=_FAKE_KEY))
    assert verdict.blocked and verdict.category == BlockCategory.CREDENTIAL


def test_needs_interrupt_is_lop_b():
    assert needs_interrupt(_action()).interrupt is True


@pytest.mark.parametrize("cron,ok", [
    ("0 8 * * *", True), ("*/5 * * * *", True), ("*/10 * * * *", True),
    ("* * * * *", False), ("*/4 * * * *", False), ("1-59 * * * *", False),
    ("garbage", False), ("", False), (None, False),
    # syntactically valid but never fires (Feb 30) — a policy verdict must be a
    # reason string at every gateway door, never a croniter exception
    ("0 0 30 2 *", False),
])
def test_cron_floor(cron, ok):
    assert (cron_floor_error(cron) is None) is ok


def test_never_firing_cron_is_a_clean_deny_not_an_exception():
    verdict = classify(_action({"daily": "0 0 30 2 *"}))
    assert verdict.blocked and verdict.category == BlockCategory.SECURITY


# --- gateway doors: both trust modes, execute() not just the chat door ---


@pytest.mark.parametrize("trust_mode", ["autonomous", "guarded"])
def test_bad_cron_hard_denied_via_execute_even_with_handler(tmp_path, trust_mode):
    gw = ActionGateway(_settings(tmp_path, trust_mode))
    ran = []
    try:
        with pytest.raises(HardBlockedError):
            gw.execute(_action({"daily": "* * * * *"}),
                       handler=lambda a: ran.append(a) or "boom")
    finally:
        gw.close()
    assert ran == []  # the handler never ran past the red line


@pytest.mark.parametrize("trust_mode", ["autonomous", "guarded"])
def test_bad_structure_never_approvable(tmp_path, trust_mode):
    """approve-reentry (execute_approved) must ALSO hold — the F1 door."""
    gw = ActionGateway(_settings(tmp_path, trust_mode))
    try:
        with pytest.raises(HardBlockedError):
            gw.execute_approved({"type": "schedule_update", "schedule": {}},
                                handler=lambda a: "boom")
    finally:
        gw.close()


def test_guarded_queues_valid_update(tmp_path):
    gw = ActionGateway(_settings(tmp_path, "guarded"))
    try:
        result = gw.execute(_action(), handler=lambda a: "would write")
        assert result.status == "pending_approval"
    finally:
        gw.close()


def test_autonomous_runs_now_with_audit_marker(tmp_path):
    gw = ActionGateway(_settings(tmp_path, "autonomous"))
    try:
        result = gw.execute(_action(), handler=lambda a: "written")
        assert result.status == "executed"
    finally:
        gw.close()
    rows = AuditLog(tmp_path / "data" / "audit" / "audit.jsonl").query(verdict="allow")
    assert rows and rows[0]["rationale"] == AUTONOMOUS_RATIONALE


# --- handler re-enforcement (self-only closure; floor/kind/caps re-checked) ---


@pytest.fixture
def agent_env(tmp_path, monkeypatch):
    """A real profiles/<id>/profile.yaml + data dir the handler can write."""
    profiles = tmp_path / "profiles"
    data_root = tmp_path / ".data"
    monkeypatch.setattr("my_crew.profile.loader._PROFILES_DIR", profiles)
    monkeypatch.setattr("my_crew.server.profile_editor._PROFILES_DIR", profiles)
    monkeypatch.setattr("my_crew.runtime.agent_paths.DATA_DIR", data_root)
    # No CEO notice in unit tests (no registry here) — patch to a no-op recorder.
    notices = []
    monkeypatch.setattr("my_crew.actions.schedule_write._notify_ceo_best_effort",
                        lambda pid, changes: notices.append((pid, changes)))
    d = profiles / "acme"
    d.mkdir(parents=True)
    (d / "profile.yaml").write_text(yaml.safe_dump({
        "name": "Acme", "domain": "pm",
        "schedule": {"daily": "0 9 * * *"},
        "reports": ["daily"],
        "budget": {"monthly_usd": 50},
    }), encoding="utf-8")
    return profiles, notices


def test_handler_merges_only_schedule_and_notifies(agent_env):
    profiles, notices = agent_env
    summary = make_schedule_update_handler("acme")(_action({"daily": "0 8 * * *"}))
    assert "daily→0 8 * * *" in summary
    doc = yaml.safe_load((profiles / "acme" / "profile.yaml").read_text())
    assert doc["schedule"] == {"daily": "0 8 * * *"}
    assert doc["name"] == "Acme" and doc["budget"] == {"monthly_usd": 50}  # untouched
    assert notices == [("acme", "daily→0 8 * * *")]


def test_handler_rejects_unknown_kind(agent_env):
    with pytest.raises(PermissionError, match="not a report of domain"):
        make_schedule_update_handler("acme")(_action({"hack-kind": "0 8 * * *"}))


def test_handler_re_enforces_floor_itself(agent_env):
    """Even if classify were bypassed entirely, the handler refuses a floor violation."""
    with pytest.raises(PermissionError, match="floor"):
        make_schedule_update_handler("acme")(_action({"daily": "* * * * *"}))


def test_handler_daily_cap(agent_env):
    handler = make_schedule_update_handler("acme")
    for i in range(5):
        handler(_action({"daily": f"{i} 8 * * *"}))
    with pytest.raises(PermissionError, match="lượt đổi lịch"):
        handler(_action({"daily": "30 8 * * *"}))


def test_handler_is_self_only_by_closure(agent_env):
    """A smuggled agent_id field changes NOTHING: the handler writes its own profile."""
    profiles, _ = agent_env
    other = profiles / "victim"
    other.mkdir()
    other_yaml = yaml.safe_dump({"name": "Victim", "domain": "pm",
                                 "schedule": {"daily": "0 9 * * *"}, "reports": ["daily"]})
    (other / "profile.yaml").write_text(other_yaml, encoding="utf-8")
    make_schedule_update_handler("acme")(
        _action({"daily": "0 7 * * *"}, agent_id="victim", profile_id="victim")
    )
    assert (other / "profile.yaml").read_text() == other_yaml  # victim untouched
    doc = yaml.safe_load((profiles / "acme" / "profile.yaml").read_text())
    assert doc["schedule"]["daily"] == "0 7 * * *"


def test_dedup_hint_state_bearing_a_b_a(tmp_path, agent_env):
    """A→B→A with state-bearing hints = three distinct dedup keys → all three run."""
    gw = ActionGateway(_settings(tmp_path, "autonomous"))
    statuses = []
    try:
        for hint in ("daily:0 8 * * *:t1", "daily:0 9 * * *:t2", "daily:0 8 * * *:t3"):
            r = gw.execute(_action({"daily": "0 8 * * *"}, dedup_hint=hint),
                           handler=make_schedule_update_handler("acme"))
            statuses.append(r.status)
    finally:
        gw.close()
    assert statuses == ["executed", "executed", "executed"]


# --- legacy CLI approve path: named refusal, no silent no-op ---


def test_legacy_dispatch_raises_named_error():
    from my_crew.actions.approved_dispatch import dispatch_approved_action

    with pytest.raises(RuntimeError, match="agent-bound handler"):
        dispatch_approved_action(_action(), config=object())


def test_agent_bound_dispatch_routes_schedule_update(agent_env):
    from my_crew.actions.approved_dispatch import make_agent_bound_dispatch

    summary = make_agent_bound_dispatch("acme", config=object())(
        _action({"daily": "0 6 * * *"})
    )
    assert "schedule updated (acme)" in summary
