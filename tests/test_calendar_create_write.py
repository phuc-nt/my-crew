"""v39 #3: Calendar-create WRITE through the Action Gateway (gws_write).

Calendar-create rides the existing gws_write type: allowlisted prefix, Lớp B (guarded
queues / autonomous audits), with delete/acl/share caught by the Lớp A marker scan. The
chat-ops command builds a CODE-fixed argv from slots — the LLM never supplies an argv.
"""

from __future__ import annotations

import json

import pytest

from my_crew.actions.hard_block import BlockCategory, _hard_deny_gws


def _gws(argv):
    return {"type": "gws_write", "argv": argv}


def test_calendar_create_is_allowlisted():
    body = json.dumps({"summary": "họp", "start": {"dateTime": "2026-07-20T09:00:00+07:00"}})
    verdict = _hard_deny_gws(_gws(["calendar", "events", "insert", "--json", body]))
    assert verdict is None  # passes Lớp A → flows as ordinary Lớp B


def test_calendar_delete_is_hard_denied():
    v = _hard_deny_gws(_gws(["calendar", "events", "delete", "--params", "{}"]))
    assert v is not None and v.category == BlockCategory.DATA_LOSS


def test_calendar_acl_grant_is_hard_denied():
    # Granting calendar access = a permission change → SECURITY red line.
    v = _hard_deny_gws(_gws(["calendar", "acl", "insert", "--json", "{}"]))
    assert v is not None and v.category == BlockCategory.SECURITY


def test_unlisted_gws_subcommand_still_denied():
    v = _hard_deny_gws(_gws(["gmail", "users", "messages", "send"]))
    assert v is not None  # outside the fixed prefix table


def test_destructive_word_in_event_title_fails_closed():
    # The marker scan reads EVERY token incl. content — a "delete" in the title is denied
    # (deliberate fail-closed false positive; content can be reworded).
    body = json.dumps(
        {"summary": "delete old records", "start": {"dateTime": "2026-07-20T09:00:00Z"}})
    v = _hard_deny_gws(_gws(["calendar", "events", "insert", "--json", body]))
    assert v is not None and v.category == BlockCategory.DATA_LOSS


# ---- ops command -----------------------------------------------------------

def test_ops_command_registered():
    from my_crew.agent.ops_catalog import get_command

    cmd = get_command("create_calendar_event")
    assert cmd is not None and cmd["readonly"] is False
    assert set(cmd["slots"]) >= {"title", "start"}


def test_build_event_body_shape():
    from my_crew.agent.ops_calendar_event import _build_event_body

    body = _build_event_body({
        "title": "Họp sprint", "start": "2026-07-20T09:00:00+07:00",
        "attendees": "a@x.com, b@y.com, bad-no-at",
    })
    assert body["summary"] == "Họp sprint"
    assert body["start"]["dateTime"] == "2026-07-20T09:00:00+07:00"
    assert body["end"] == body["start"]  # end defaults to start
    assert body["attendees"] == [{"email": "a@x.com"}, {"email": "b@y.com"}]  # bad one dropped


def test_build_event_body_requires_title_and_start():
    from my_crew.agent.ops_calendar_event import _build_event_body

    with pytest.raises(ValueError, match="tiêu đề"):
        _build_event_body({"start": "2026-07-20T09:00:00Z"})


@pytest.mark.parametrize("status,phrase", [
    ("executed", "Đã tạo"),
    ("pending_approval", "chờ duyệt"),
    ("dry_run", "DRY_RUN"),
    ("deduplicated", "KHÔNG tạo"),
    ("skipped", "KHÔNG tạo được"),
])
def test_ops_reply_reports_status_honestly(status, phrase, monkeypatch):
    from my_crew.actions.action_gateway import GatewayResult
    from my_crew.agent import ops_calendar_event

    class _Loaded:
        settings = object()
        config = object()

    monkeypatch.setattr(ops_calendar_event, "_sender_profile", lambda: _Loaded())

    class _GW:
        def execute(self, action, *, handler=None, rationale=""):
            return GatewayResult(status=status, summary="x")

    monkeypatch.setattr("my_crew.actions.action_gateway.ActionGateway", lambda *a, **k: _GW())
    out = ops_calendar_event.run_create_calendar_event(
        {"title": "họp", "start": "2026-07-20T09:00:00+07:00"})
    assert phrase in out


def test_ops_builds_fixed_argv_not_llm_supplied(monkeypatch):
    """The argv is CODE-built: subcommand fixed, slots only fill the --json body."""
    from my_crew.actions.action_gateway import GatewayResult
    from my_crew.agent import ops_calendar_event

    class _Loaded:
        settings = object()
        config = object()

    captured = {}

    class _GW:
        def execute(self, action, *, handler=None, rationale=""):
            captured["action"] = action
            return GatewayResult(status="executed", summary="ok")

    monkeypatch.setattr(ops_calendar_event, "_sender_profile", lambda: _Loaded())
    monkeypatch.setattr("my_crew.actions.action_gateway.ActionGateway", lambda *a, **k: _GW())
    ops_calendar_event.run_create_calendar_event(
        {"title": "họp", "start": "2026-07-20T09:00:00+07:00"})
    argv = captured["action"]["argv"]
    assert argv[:4] == ["calendar", "events", "insert", "--json"]  # fixed prefix
    assert captured["action"]["type"] == "gws_write"
