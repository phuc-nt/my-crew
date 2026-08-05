"""Chat as the third surface on the Lớp B approval queue (v69).

What these tests defend, in order of how badly a regression would hurt:

1. A standing rule is described in WORDS that match what it actually binds — and is
   refused outright when chat cannot describe the action at all.
2. A lost race (web/CLI decided first) is reported as such and teaches NO rule.
3. Lớp A survives the human tap: a hard block is a refusal, not a retry prompt.
4. The `(agent_id, approval_id)` pair is bound at preview and never re-resolved.
"""

from __future__ import annotations

import pytest

from my_crew.actions.action_gateway import ActionGateway
from my_crew.agent import ops_approvals
from my_crew.audit.audit_log import AuditLog

EMAIL = {"type": "email_send", "to": "ceo@acme.com", "subject": "hi", "body": "chi tiết"}
TEAM_TASK = {"type": "team_task_create", "title": "làm báo cáo", "assignee": "researcher"}


@pytest.fixture
def dispatch_ok(monkeypatch):
    """Stub the post itself.

    Tests that use this are asserting on which ROW got consumed and what rule was
    learned — not on whether SMTP or the team-task roster is configured. The gateway,
    the compare-and-set, and the rule derivation all still run for real.
    """
    monkeypatch.setattr(
        "my_crew.actions.approved_dispatch.dispatch_approved_action",
        lambda action, config: "SENT",
    )


@pytest.fixture
def agent(monkeypatch, tmp_path, settings_factory):
    """One enabled agent whose approval store lives under tmp_path.

    Both the reader (`agent_data_dir`) and the writer (`_gateway` via `load_profile`) are
    pointed at the SAME dir, because the whole point of these commands is that chat reads
    and decides the same rows the CLI does.
    """
    settings = settings_factory(dry_run=False)
    data_dir = settings.data_dir

    monkeypatch.setattr(ops_approvals, "_enabled_agent_ids", lambda: ["secretary"])
    monkeypatch.setattr(ops_approvals, "agent_data_dir", lambda _id: data_dir)

    class _Loaded:
        profile_id = "secretary"

    _Loaded.settings = settings
    _Loaded.config = type("C", (), {"slack_external_channels": ()})()

    def _load_profile(agent_id, data_dir=None):
        return _Loaded

    monkeypatch.setattr("my_crew.profile.loader.load_profile", _load_profile)
    return settings, data_dir


def _queue(settings, tmp_path, action=EMAIL):
    """Queue one Lớp B action the way an agent really would, and return its id."""
    gw = ActionGateway(
        settings=settings,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        notify_enqueued=lambda *a: None,
    )
    try:
        return gw.execute(action, handler=lambda a: "SENT").approval_id
    finally:
        gw.close()


# --- listing ---


def test_listing_names_the_agent_so_the_id_is_actionable(agent, tmp_path):
    """An id alone is useless — `duyệt 3` needs to know WHOSE queue #3 is in."""
    settings, _ = agent
    approval_id = _queue(settings, tmp_path)
    out = ops_approvals.run_list_approvals({})
    assert f"#{approval_id}" in out
    assert "secretary" in out
    assert "ceo@acme.com" in out


def test_listing_an_empty_queue_says_so(agent):
    assert "Không có việc nào đang chờ duyệt" in ops_approvals.run_list_approvals({})


def test_an_unreadable_queue_is_reported_not_silently_dropped(agent, monkeypatch):
    """"Nothing pending" and "could not read" must not look identical to someone
    deciding whether to go check the web."""
    def _boom(_dir):
        raise RuntimeError("db hỏng")

    monkeypatch.setattr(ops_approvals, "read_pending_actions", _boom)
    out = ops_approvals.run_list_approvals({})
    assert "chưa đọc được" in out
    assert "secretary" in out


def test_the_listing_never_leaks_the_email_body(agent, tmp_path):
    settings, _ = agent
    _queue(settings, tmp_path)
    assert "chi tiết" not in ops_approvals.run_list_approvals({})


# --- preview ---


def test_preview_shows_what_will_happen_and_asks_to_confirm(agent, tmp_path):
    settings, _ = agent
    approval_id = _queue(settings, tmp_path)
    out = ops_approvals.preview_approve_pending_action(
        {"approval_id": str(approval_id), "agent_id": "secretary"}
    )
    assert "DUYỆT" in out
    assert "ceo@acme.com" in out
    assert "Xác nhận?" in out


def test_preview_of_a_standing_rule_spells_out_the_scope_in_words(agent, tmp_path):
    settings, _ = agent
    approval_id = _queue(settings, tmp_path)
    out = ops_approvals.preview_approve_pending_action(
        {"approval_id": str(approval_id), "agent_id": "secretary", "scope": "luôn"}
    )
    assert "MỌI email gửi tới @acme.com" in out


def test_preview_never_shows_the_params_hash(agent, tmp_path):
    """A blind hash proves nothing to the CEO — consenting to it is consenting blind."""
    from my_crew.actions.approval_rule_store import derive_rule_key

    settings, _ = agent
    approval_id = _queue(settings, tmp_path)
    _, params_hash = derive_rule_key(EMAIL)
    out = ops_approvals.preview_approve_pending_action(
        {"approval_id": str(approval_id), "agent_id": "secretary", "scope": "luôn"}
    )
    assert params_hash and params_hash not in out


def test_an_agent_wide_rule_says_it_covers_every_action_of_that_type(agent, tmp_path):
    """`params_hash is None` = one tap teaches a rule over EVERY such action. The
    broadest case must read as the broadest case."""
    settings, _ = agent
    approval_id = _queue(settings, tmp_path, TEAM_TASK)
    out = ops_approvals.preview_approve_pending_action(
        {"approval_id": str(approval_id), "agent_id": "secretary", "scope": "luôn"}
    )
    assert "MỌI thao tác `team_task_create` của agent này" in out


def test_a_deny_preview_states_the_guarded_only_limit(agent, tmp_path):
    settings, _ = agent
    approval_id = _queue(settings, tmp_path)
    out = ops_approvals.preview_reject_pending_action(
        {"approval_id": str(approval_id), "agent_id": "secretary", "scope": "chặn"}
    )
    assert "guarded" in out


def test_a_standing_rule_is_refused_when_the_action_is_only_a_stub(agent, tmp_path,
                                                                  monkeypatch):
    """Chat could not describe this action. Consent to a permanent rule over a
    description like that is not consent."""
    settings, _ = agent
    approval_id = _queue(settings, tmp_path)
    monkeypatch.setattr(ops_approvals, "is_stub_summary", lambda a: True)
    with pytest.raises(ValueError, match="không tạo luật lâu dài"):
        ops_approvals.preview_approve_pending_action(
            {"approval_id": str(approval_id), "agent_id": "secretary", "scope": "luôn"}
        )


def test_a_one_off_decision_on_a_stub_is_still_allowed(agent, tmp_path, monkeypatch):
    settings, _ = agent
    approval_id = _queue(settings, tmp_path)
    monkeypatch.setattr(ops_approvals, "is_stub_summary", lambda a: True)
    out = ops_approvals.preview_approve_pending_action(
        {"approval_id": str(approval_id), "agent_id": "secretary"}
    )
    assert "Xác nhận?" in out


def test_preview_refuses_an_agent_the_registry_does_not_serve(agent):
    with pytest.raises(ValueError, match="không có agent"):
        ops_approvals.preview_approve_pending_action(
            {"approval_id": "1", "agent_id": "kẻ-lạ"}
        )


def test_preview_refuses_a_non_numeric_id(agent):
    with pytest.raises(ValueError, match="phải là một con số"):
        ops_approvals.preview_approve_pending_action(
            {"approval_id": "mới nhất", "agent_id": "secretary"}
        )


def test_preview_refuses_a_row_that_is_no_longer_pending(agent):
    """At PREVIEW a missing row is bad input — the CEO named an id that isn't waiting,
    so it refuses and asks again rather than reporting a race that never happened."""
    with pytest.raises(ValueError, match="không còn ở trạng thái chờ"):
        ops_approvals.preview_approve_pending_action(
            {"approval_id": "9999", "agent_id": "secretary"}
        )


# --- decide ---


def test_approving_runs_the_action_and_consumes_the_row(agent, dispatch_ok, tmp_path):
    settings, data_dir = agent
    approval_id = _queue(settings, tmp_path)
    out = ops_approvals.run_approve_pending_action(
        {"approval_id": str(approval_id), "agent_id": "secretary"}
    )
    assert f"Đã duyệt #{approval_id}" in out
    from my_crew.runtime.agent_state_reader import read_pending_actions

    assert read_pending_actions(data_dir) == []


def test_rejecting_consumes_the_row_without_running_it(agent, tmp_path):
    settings, data_dir = agent
    approval_id = _queue(settings, tmp_path)
    out = ops_approvals.run_reject_pending_action(
        {"approval_id": str(approval_id), "agent_id": "secretary"}
    )
    assert f"Đã từ chối #{approval_id}" in out
    from my_crew.runtime.agent_state_reader import read_pending_actions

    assert read_pending_actions(data_dir) == []


def test_approving_with_always_learns_the_rule_from_the_stored_action(agent, dispatch_ok,
                                                                     tmp_path):
    """The rule is derived from what was APPROVED, never from anything hand-typed."""
    settings, _ = agent
    approval_id = _queue(settings, tmp_path)
    out = ops_approvals.run_approve_pending_action(
        {"approval_id": str(approval_id), "agent_id": "secretary", "scope": "luôn"}
    )
    assert "luật TỰ DUYỆT" in out

    gw = ActionGateway(settings=settings, notify_enqueued=lambda *a: None)
    try:
        rules = gw.approval_rules.list_rules()
        assert [r.scope for r in rules] == ["always"]
        assert rules[0].pattern_key == "email"
        assert "ops-chat" in rules[0].created_by
        # And it really fires: the same action no longer stops for a human.
        assert gw.approval_rules.match(EMAIL) is not None
    finally:
        gw.close()


def test_a_deny_rule_ack_always_states_the_guarded_only_limit(agent, tmp_path):
    settings, _ = agent
    approval_id = _queue(settings, tmp_path)
    out = ops_approvals.run_reject_pending_action(
        {"approval_id": str(approval_id), "agent_id": "secretary", "scope": "chặn"}
    )
    assert "guarded" in out
    assert "autonomous" in out


def test_a_plain_decision_teaches_no_rule(agent, tmp_path):
    settings, _ = agent
    approval_id = _queue(settings, tmp_path)
    ops_approvals.run_approve_pending_action(
        {"approval_id": str(approval_id), "agent_id": "secretary"}
    )
    gw = ActionGateway(settings=settings, notify_enqueued=lambda *a: None)
    try:
        assert gw.approval_rules.list_rules() == []
    finally:
        gw.close()


def test_an_unrecognized_scope_word_decides_once_and_never_teaches_a_rule(agent, tmp_path):
    """The failure direction of a misread scope must be "decided this row", never
    "created a standing rule"."""
    settings, _ = agent
    approval_id = _queue(settings, tmp_path)
    out = ops_approvals.run_approve_pending_action(
        {"approval_id": str(approval_id), "agent_id": "secretary", "scope": "ừ thì cũng được"}
    )
    assert "luật" not in out
    gw = ActionGateway(settings=settings, notify_enqueued=lambda *a: None)
    try:
        assert gw.approval_rules.list_rules() == []
    finally:
        gw.close()


# --- the three failure outcomes ---


def test_a_row_decided_by_another_surface_is_reported_as_such(agent, tmp_path):
    """Web/CLI got there first. Chat must not claim a decision it did not make.

    Reported as a lost race, NOT as bad input: the CEO typed a valid id and someone else
    got there first — "you typed something wrong" would be a lie.
    """
    settings, _ = agent
    approval_id = _queue(settings, tmp_path)
    slots = {"approval_id": str(approval_id), "agent_id": "secretary"}
    # Bind the ids (as preview does), THEN let another surface decide the row.
    gw = ActionGateway(settings=settings, notify_enqueued=lambda *a: None)
    try:
        gw.reject(approval_id)
    finally:
        gw.close()
    out = ops_approvals.run_approve_pending_action(slots)
    assert "đã được xử lý trước đó" in out


def test_losing_the_race_inside_the_gateway_teaches_no_rule(agent, tmp_path, monkeypatch):
    """The narrow window: the row is still pending at re-read, and another surface wins
    between that read and the transition. A rule learned here would be a rule taught from
    a decision that was not ours."""
    settings, _ = agent
    approval_id = _queue(settings, tmp_path)

    real_approve = ActionGateway.approve

    def _lose(self, aid, *, handler):
        self._approvals.transition_if_pending(aid, "rejected")  # another surface wins
        return real_approve(self, aid, handler=handler)

    monkeypatch.setattr(ActionGateway, "approve", _lose)
    out = ops_approvals.run_approve_pending_action(
        {"approval_id": str(approval_id), "agent_id": "secretary", "scope": "luôn"}
    )
    assert "đã được xử lý trước đó" in out

    monkeypatch.undo()
    gw = ActionGateway(settings=settings, notify_enqueued=lambda *a: None)
    try:
        assert gw.approval_rules.list_rules() == []
    finally:
        gw.close()


def test_a_hard_block_is_a_refusal_not_a_retry_prompt(agent, tmp_path, monkeypatch):
    """Lớp A denies even an approved action, and no human tap overrides it. Reporting it
    as retryable would send the CEO tapping at a wall."""
    from my_crew.actions.action_gateway import HardBlockedError

    settings, _ = agent
    approval_id = _queue(settings, tmp_path)

    def _blocked(self, aid, *, handler):
        raise HardBlockedError("Lớp A hard-block (security)")

    monkeypatch.setattr(ActionGateway, "approve", _blocked)
    out = ops_approvals.run_approve_pending_action(
        {"approval_id": str(approval_id), "agent_id": "secretary"}
    )
    assert "Lớp A chặn" in out
    assert "thử lại" not in out


def test_a_hard_block_teaches_no_rule(agent, tmp_path, monkeypatch):
    """A standing "always" over an action Lớp A blocks can only ever be wrong."""
    from my_crew.actions.action_gateway import HardBlockedError

    settings, _ = agent
    approval_id = _queue(settings, tmp_path)

    def _blocked(self, aid, *, handler):
        raise HardBlockedError("Lớp A hard-block (security)")

    monkeypatch.setattr(ActionGateway, "approve", _blocked)
    ops_approvals.run_approve_pending_action(
        {"approval_id": str(approval_id), "agent_id": "secretary", "scope": "luôn"}
    )
    monkeypatch.undo()
    gw = ActionGateway(settings=settings, notify_enqueued=lambda *a: None)
    try:
        assert gw.approval_rules.list_rules() == []
    finally:
        gw.close()


def test_a_failed_post_says_the_row_is_still_pending(agent, tmp_path, monkeypatch):
    """The gateway reverted it — the CEO can simply retry, and must be told so rather
    than left guessing whether the email went out."""
    settings, _ = agent
    approval_id = _queue(settings, tmp_path)

    def _fail(self, aid, *, handler):
        raise RuntimeError("smtp chết")

    monkeypatch.setattr(ActionGateway, "approve", _fail)
    out = ops_approvals.run_approve_pending_action(
        {"approval_id": str(approval_id), "agent_id": "secretary"}
    )
    assert "VẪN ĐANG CHỜ DUYỆT" in out
    assert "thử lại" in out


def test_a_failed_post_teaches_no_rule(agent, tmp_path, monkeypatch):
    settings, _ = agent
    approval_id = _queue(settings, tmp_path)

    def _fail(self, aid, *, handler):
        raise RuntimeError("smtp chết")

    monkeypatch.setattr(ActionGateway, "approve", _fail)
    ops_approvals.run_approve_pending_action(
        {"approval_id": str(approval_id), "agent_id": "secretary", "scope": "luôn"}
    )
    monkeypatch.undo()
    gw = ActionGateway(settings=settings, notify_enqueued=lambda *a: None)
    try:
        assert gw.approval_rules.list_rules() == []
    finally:
        gw.close()


# --- binding ---


def test_the_confirmed_row_is_the_previewed_row_not_the_newest(agent, dispatch_ok,
                                                               tmp_path):
    """The v64 H1 lesson. A push landing between preview and confirm must not move the
    target: the ids ride in the draft slots, so the SECOND row stays untouched."""
    settings, data_dir = agent
    first = _queue(settings, tmp_path)
    slots = {"approval_id": str(first), "agent_id": "secretary"}
    ops_approvals.preview_approve_pending_action(slots)

    second = _queue(settings, tmp_path, TEAM_TASK)  # arrives mid-conversation
    ops_approvals.run_approve_pending_action(slots)

    from my_crew.runtime.agent_state_reader import read_pending_actions

    still_pending = [r["id"] for r in read_pending_actions(data_dir)]
    assert still_pending == [second]


# --- catalog wiring ---


def test_the_commands_are_admin_only():
    """These reach into OTHER agents' approval stores — fleet authority, not orchestration."""
    from my_crew.agent.ops_catalog import catalog_for_domain

    personal = catalog_for_domain("personal")
    admin = catalog_for_domain("admin")
    for cid in ("list_approvals", "approve_pending_action", "reject_pending_action"):
        assert cid in admin
        assert cid not in personal


def test_the_two_deciding_commands_require_a_confirm_step():
    """A command that runs a queued action must never be readonly (readonly commands
    skip the preview/confirm gate entirely)."""
    from my_crew.agent.ops_catalog import OPS_COMMANDS

    for cid in ("approve_pending_action", "reject_pending_action"):
        assert OPS_COMMANDS[cid]["readonly"] is False
        assert "preview" in OPS_COMMANDS[cid]
    assert OPS_COMMANDS["list_approvals"]["readonly"] is True
