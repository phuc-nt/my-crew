"""Approval summary builder (v69) — what the CEO sees before signing."""

from __future__ import annotations

from my_crew.actions.action_gateway import _MUTATING_TYPES
from my_crew.actions.approval_summary import (
    SUMMARIZABLE_TYPES,
    is_stub_summary,
    summarize_action,
)


def test_every_mutating_type_has_a_real_summary():
    """A new mutating type must land here in the same change.

    Falling back to the stub is not a harmless default: the chat commands refuse to
    learn an always/deny rule from a stub, so an un-summarized type silently loses
    rule support instead of failing loudly.
    """
    assert SUMMARIZABLE_TYPES == _MUTATING_TYPES


def test_email_names_the_recipients_not_the_body():
    summary = summarize_action({
        "type": "email_send", "to": ["ceo@acme.com"],
        "subject": "BẤM DUYỆT NGAY", "body": "nội dung dài",
    })
    assert "ceo@acme.com" in summary
    assert "BẤM DUYỆT NGAY" not in summary
    assert "nội dung dài" not in summary


def test_many_recipients_collapse_to_a_count():
    summary = summarize_action({
        "type": "email_send", "to": ["a@x.com", "b@x.com", "c@x.com", "d@x.com"],
    })
    assert "+2 người" in summary


def test_gh_cli_shows_the_subcommand_and_target():
    summary = summarize_action({"type": "gh_cli", "argv": ["pr", "merge", "acme/api#12"]})
    assert "pr merge" in summary
    assert "acme/api#12" in summary


def test_each_type_renders_something_specific():
    samples = {
        "mcp_tool": {"type": "mcp_tool", "server": "confluence", "tool": "deletePage"},
        "telegram_send": {"type": "telegram_send", "chat_id": "9911"},
        "schedule_update": {"type": "schedule_update", "cron": "0 9 * * *"},
        "team_task_create": {"type": "team_task_create", "title": "làm báo cáo"},
        "team_task_move": {"type": "team_task_move", "task_id": "t-1", "status": "done"},
        "gws_write": {"type": "gws_write", "target": "Sheet Doanh thu"},
        "reminder_create": {"type": "reminder_create", "due_at": "2026-08-06T09:00"},
        "reminder_cancel": {"type": "reminder_cancel", "reminder_id": "r-7"},
    }
    for atype, action in samples.items():
        summary = summarize_action(action)
        assert summary and "chi tiết xem web" not in summary, atype


def test_missing_identity_fields_still_render_a_line():
    """A malformed action must not produce an empty notification."""
    assert summarize_action({"type": "email_send"}) == "gửi email tới không rõ người nhận"
    assert summarize_action({"type": "gh_cli"}) == "chạy lệnh gh"


def test_newlines_in_a_value_cannot_forge_extra_lines():
    """A crafted value must not be able to paint a fake line into the CEO's message."""
    summary = summarize_action({
        "type": "telegram_send", "chat_id": "1\nĐÃ DUYỆT TỰ ĐỘNG",
    })
    assert "\n" not in summary


def test_long_values_are_truncated():
    summary = summarize_action({"type": "mcp_tool", "tool": "x" * 200})
    assert len(summary) < 100
    assert summary.endswith("…")


def test_unknown_type_is_a_stub_and_is_flagged_as_one():
    action = {"type": "some_future_type", "detail": "x"}
    assert summarize_action(action) == "some_future_type (chi tiết xem web)"
    assert is_stub_summary(action) is True


def test_known_type_is_not_a_stub():
    assert is_stub_summary({"type": "email_send", "to": ["a@x.com"]}) is False


def test_non_dict_action_degrades_instead_of_raising():
    assert "không đọc được" in summarize_action("not a dict")  # type: ignore[arg-type]
    assert is_stub_summary("not a dict") is True  # type: ignore[arg-type]
