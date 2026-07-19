"""Office room event projection (v12 M29): the PII firewall applied at write time.

Load-bearing:
- Each known kind returns EXACTLY its documented allowlist (no extra/unlisted field
  leaks through, matching what a caller could stuff into `body`).
- A field outside a kind's allowlist (e.g. an email/phone smuggled in as an extra key)
  never appears in the projected dict.
- Unknown kind -> {} (drop everything, safe default).
- Long free text is truncated with the explicit ellipsis marker.
"""

from __future__ import annotations

from my_crew.server.office_event_projection import VALID_KINDS, summarize_office_event


def test_ceo_kind_keeps_only_text():
    out = summarize_office_event("ceo", {"text": "chuẩn bị demo", "secret": "leak-me"})
    assert out == {"text": "chuẩn bị demo"}
    assert "secret" not in out


def test_assignment_kind_allowlist():
    out = summarize_office_event(
        "assignment",
        {"task_title": "Demo", "step_count": 3, "summary": "Phân công: a, b", "extra": "x"},
    )
    # v15: `pic`/`task_id` joined the allowlist (empty when the writer omits them).
    assert out == {"task_title": "Demo", "step_count": 3, "summary": "Phân công: a, b",
                   "pic": "", "task_id": ""}


def test_step_status_kind_allowlist():
    out = summarize_office_event(
        "step_status",
        {"task_title": "Demo", "step_title": "draft", "status": "started",
         "assigned_to": "agent-a", "phase": "dang-lam", "attempt_id": "att-1", "leak": "pii"},
    )
    assert out == {"task_title": "Demo", "step_title": "draft", "status": "started",
                   "assigned_to": "agent-a", "phase": "dang-lam", "attempt_id": "att-1"}
    assert "leak" not in out


def test_step_status_phase_outside_closed_set_is_dropped_not_truncated():
    # `phase` is a closed enum (see `team_task_graph.PHASE_WORK/PHASE_SELF_CHECK/
    # PHASE_REWORK`), same posture as `review`'s `verdict` — an unrecognized value
    # (a bug upstream, or a future phase tag not yet wired here) must be dropped to
    # "" entirely, not merely length-capped and passed through.
    out = summarize_office_event(
        "step_status",
        {"task_title": "Demo", "step_title": "draft", "status": "started",
         "assigned_to": "agent-a", "phase": "not-a-real-phase", "attempt_id": "att-1"},
    )
    assert out["phase"] == ""


def test_step_status_phase_each_closed_set_value_passes_through():
    for phase in ("dang-lam", "tu-soat", "dang-sua"):
        out = summarize_office_event(
            "step_status",
            {"task_title": "Demo", "step_title": "draft", "status": "started",
             "assigned_to": "agent-a", "phase": phase, "attempt_id": "att-1"},
        )
        assert out["phase"] == phase


def test_handoff_kind_allowlist():
    out = summarize_office_event(
        "handoff",
        {"task_title": "Demo", "step_title": "draft", "message": "xong rồi",
         "assigned_to": "agent-a", "email": "a@b.com"},
    )
    assert out == {"task_title": "Demo", "step_title": "draft", "message": "xong rồi",
                   "assigned_to": "agent-a"}
    assert "email" not in out


def test_milestone_kind_allowlist():
    out = summarize_office_event(
        "milestone",
        {"task_id": "t1", "task_title": "Demo", "milestone": "done", "message": "hoàn tất",
         "phone": "0900000000"},
    )
    assert out == {
        "task_id": "t1", "task_title": "Demo", "milestone": "done", "message": "hoàn tất",
    }
    assert "phone" not in out


def test_step_status_deep_team_present_only_when_true():
    # v54: `deep_team` is carried ONLY when the producer set it true — omitted (not a
    # `False` key) when absent, keeping every pre-v54 event's key set unchanged.
    out_true = summarize_office_event(
        "step_status",
        {"task_title": "Demo", "step_title": "draft", "status": "started",
         "assigned_to": "agent-a", "deep_team": True},
    )
    assert out_true["deep_team"] is True

    out_false = summarize_office_event(
        "step_status",
        {"task_title": "Demo", "step_title": "draft", "status": "started",
         "assigned_to": "agent-a"},
    )
    assert "deep_team" not in out_false


def test_external_action_kind_allowlist_no_content_echo():
    out = summarize_office_event(
        "external_action",
        {
            "actor": "hr", "tool": "slack:post_message", "action_type": "mcp_tool",
            "outcome": "allow", "detail": "C1",
            "message": "should never leak", "args": {"text": "secret payload"},
        },
    )
    assert out == {
        "actor": "hr", "tool": "slack:post_message", "action_type": "mcp_tool",
        "outcome": "allow", "detail": "C1",
    }
    assert "message" not in out and "args" not in out


def test_unknown_kind_drops_everything():
    assert summarize_office_event("weird-new-kind", {"text": "should not survive"}) == {}


def test_missing_fields_default_to_empty_not_keyerror():
    assert summarize_office_event("ceo", {}) == {"text": ""}
    assert summarize_office_event("assignment", {}) == {
        "task_title": "", "step_count": 0, "summary": "", "pic": "", "task_id": "",
    }
    assert summarize_office_event("step_status", {}) == {
        "task_title": "", "step_title": "", "status": "", "assigned_to": "",
        "phase": "", "attempt_id": "",
    }


def test_long_text_is_truncated_with_marker():
    long_text = "x" * 1000
    out = summarize_office_event("ceo", {"text": long_text})
    assert len(out["text"]) < 1000
    assert out["text"].endswith("…")


def test_valid_kinds_matches_projection_switch():
    for kind in VALID_KINDS:
        # every VALID_KINDS member must be handled (non-{} output for a body with content)
        assert summarize_office_event(kind, {"task_title": "t", "text": "t"}) != {}
