"""Unit tests for the learned-approval rule store + shared key derivation."""

from __future__ import annotations

import pytest

from my_crew.actions.approval_rule_store import (
    SCOPE_ALWAYS,
    SCOPE_DENY,
    ApprovalRuleStore,
    derive_rule_key,
)


@pytest.fixture()
def store(tmp_path):
    s = ApprovalRuleStore(tmp_path / "approvals.db")
    yield s
    s.close()


# --- derive_rule_key -------------------------------------------------------

def test_mcp_tool_binds_channel():
    a = {"type": "mcp_tool", "server": "slack", "tool": "post_message",
         "args": {"channel": "C123"}}
    pat, ph = derive_rule_key(a)
    assert pat == "mcp:slack:post_message"
    assert ph is not None
    # Same tool, different channel → different hash (miss).
    b = {**a, "args": {"channel": "C999"}}
    _, ph2 = derive_rule_key(b)
    assert ph2 != ph


def test_mcp_tool_binds_linear_issue_id():
    """linear_write sends `args.issueId` (camelCase). A rule taught on one issue must NOT
    match a comment aimed at a different issue."""
    a = {"type": "mcp_tool", "server": "linear", "tool": "create_comment",
         "args": {"issueId": "ENG-1", "body": "ok"}}
    pat, ph = derive_rule_key(a)
    assert pat == "mcp:linear:create_comment"
    assert ph is not None  # must bind, never a NULL (match-anything) hash
    _, ph2 = derive_rule_key({**a, "args": {"issueId": "FINANCE-42", "body": "ok"}})
    assert ph2 != ph


def test_mcp_tool_binds_confluence_space_id():
    """confluence_write sends `args.spaceId`. A different space must miss."""
    a = {"type": "mcp_tool", "server": "confluence", "tool": "create_page",
         "args": {"spaceId": "SPACE_A", "title": "t", "content": "c"}}
    pat, ph = derive_rule_key(a)
    assert pat == "mcp:confluence:create_page"
    assert ph is not None
    _, ph2 = derive_rule_key({**a, "args": {"spaceId": "SPACE_B", "title": "t",
                                            "content": "c"}})
    assert ph2 != ph


def test_mcp_tool_without_known_destination_key_binds_whole_args():
    """An unrecognized arg shape must never collapse to a NULL bind — otherwise one taught
    rule would auto-approve a write to any other target of the same tool."""
    a = {"type": "mcp_tool", "server": "x", "tool": "write", "args": {"weird": "TARGET_A"}}
    _, ph = derive_rule_key(a)
    assert ph is not None
    _, ph2 = derive_rule_key({**a, "args": {"weird": "TARGET_B"}})
    assert ph2 != ph


def test_always_rule_does_not_leak_across_linear_issues(store):
    """End-to-end at the store: teaching ALWAYS on ENG-1 must not match FINANCE-42."""
    taught = {"type": "mcp_tool", "server": "linear", "tool": "create_comment",
              "args": {"issueId": "ENG-1", "body": "ship it"}}
    store.add_rule(taught, scope=SCOPE_ALWAYS, created_by="ceo")
    assert store.match(taught) is not None
    other = {**taught, "args": {"issueId": "FINANCE-42", "body": "ship it"}}
    assert store.match(other) is None


def test_email_binds_recipient_domain():
    a = {"type": "email_send", "to": "alice@acme.com"}
    pat, ph = derive_rule_key(a)
    assert pat == "email"
    assert ph is not None
    # Same domain, different local part → SAME hash (bind on domain).
    _, ph_same = derive_rule_key({"type": "email_send", "to": "bob@acme.com"})
    assert ph_same == ph
    # Different domain → different hash.
    _, ph_diff = derive_rule_key({"type": "email_send", "to": "eve@evil.com"})
    assert ph_diff != ph


def test_telegram_binds_chat_id():
    pat, ph = derive_rule_key({"type": "telegram_send", "chat_id": "42", "text": "hi"})
    assert pat == "telegram"
    _, ph2 = derive_rule_key({"type": "telegram_send", "chat_id": "43", "text": "hi"})
    assert ph2 != ph


def test_gh_cli_binds_repo():
    a = {"type": "gh_cli", "argv": ["pr", "merge", "-R", "me/repo", "5"]}
    pat, ph = derive_rule_key(a)
    assert pat == "gh:pr merge"
    _, ph_other = derive_rule_key(
        {"type": "gh_cli", "argv": ["pr", "merge", "-R", "me/other", "5"]}
    )
    assert ph_other != ph


def test_gws_write_binds_target():
    a = {"type": "gws_write", "argv": ["sheets", "+append", "SHEET_A", "data"]}
    pat, ph = derive_rule_key(a)
    assert pat == "gws:sheets"
    _, ph2 = derive_rule_key(
        {"type": "gws_write", "argv": ["sheets", "+append", "SHEET_B", "data"]}
    )
    assert ph2 != ph


@pytest.mark.parametrize(
    "action",
    [
        {"type": "email_send", "to": "ceo@acme.com", "subject": "s",
         "body": "key ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345 here"},
        {"type": "mcp_tool", "server": "slack", "tool": "post_message",
         "args": {"channel": "C123", "text": "tok xoxb-1234567890-abcdefghij"}},
        {"type": "gh_cli",
         "argv": ["pr", "merge", "-R", "me/repo", "5", "--body",
                  "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"]},
    ],
)
def test_redaction_does_not_move_the_bind(action):
    """The CLI learns a rule from the REDACTED stored action while the gateway matches the
    LIVE one. A secret in a non-bound field must be redacted without changing the key, or a
    taught rule would never fire."""
    from my_crew.actions.secret_patterns import redact

    stored = redact(action)
    assert stored != action, "test needs a secret the redactor actually matches"
    assert derive_rule_key(stored) == derive_rule_key(action)


def test_secret_shaped_destination_fails_closed():
    """The one case where redacted and live keys CAN diverge: the destination id is itself
    secret-shaped. The rule then does not fire and the action stays queued for a human —
    fail-closed. It must never resolve the other way (auto-approving an untaught target)."""
    from my_crew.actions.secret_patterns import redact

    live = {"type": "mcp_tool", "server": "slack", "tool": "post_message",
            "args": {"channel": "xoxb-1234567890-abcdefghij", "text": "hi"}}
    assert derive_rule_key(redact(live)) != derive_rule_key(live)


def test_internal_types_have_null_bind():
    for t in ("team_task_create", "team_task_move", "schedule_update",
              "reminder_create", "reminder_cancel"):
        pat, ph = derive_rule_key({"type": t})
        assert pat == t
        assert ph is None


# --- match / add / deny-wins ----------------------------------------------

def test_always_rule_matches_same_action(store):
    a = {"type": "mcp_tool", "server": "slack", "tool": "post_message",
         "args": {"channel": "C1"}}
    store.add_rule(a, scope=SCOPE_ALWAYS, created_by="ceo")
    m = store.match(a)
    assert m is not None and m.scope == SCOPE_ALWAYS


def test_changed_param_misses(store):
    a = {"type": "mcp_tool", "server": "slack", "tool": "post_message",
         "args": {"channel": "C1"}}
    store.add_rule(a, scope=SCOPE_ALWAYS, created_by="ceo")
    b = {**a, "args": {"channel": "C2"}}
    assert store.match(b) is None


def test_deny_wins_over_always(store):
    a = {"type": "email_send", "to": "x@acme.com"}
    store.add_rule(a, scope=SCOPE_ALWAYS, created_by="ceo")
    store.add_rule(a, scope=SCOPE_DENY, created_by="ceo")
    m = store.match(a)
    assert m is not None and m.scope == SCOPE_DENY


def test_add_rule_idempotent(store):
    a = {"type": "telegram_send", "chat_id": "9", "text": "t"}
    r1 = store.add_rule(a, scope=SCOPE_ALWAYS, created_by="ceo")
    r2 = store.add_rule(a, scope=SCOPE_ALWAYS, created_by="ceo")
    assert r1.id == r2.id
    assert len(store.list_rules()) == 1


def test_revoke_deactivates(store):
    a = {"type": "mcp_tool", "server": "slack", "tool": "post_message",
         "args": {"channel": "C1"}}
    r = store.add_rule(a, scope=SCOPE_ALWAYS, created_by="ceo")
    assert store.is_active(r.id)
    assert store.revoke(r.id) is True
    assert store.match(a) is None
    assert store.is_active(r.id) is False
    # Second revoke is a no-op.
    assert store.revoke(r.id) is False


def test_record_use_bumps_count(store):
    a = {"type": "email_send", "to": "x@acme.com"}
    r = store.add_rule(a, scope=SCOPE_ALWAYS, created_by="ceo")
    store.record_use(r.id)
    store.record_use(r.id)
    got = store.get(r.id)
    assert got is not None and got.use_count == 2
    assert got.last_used_at is not None


def test_add_rule_rejects_bad_scope(store):
    with pytest.raises(ValueError):
        store.add_rule({"type": "email_send", "to": "x@acme.com"},
                       scope="once", created_by="ceo")
