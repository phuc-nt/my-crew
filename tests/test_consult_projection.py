"""`office_event_projection.summarize_office_event("consult", ...)` (M33): the
write-time PII firewall for consult room events.

Load-bearing:
- allowlist keeps ONLY from/to/question_summary/answer_summary/attempt_id — any other
  field in the raw body is dropped (same "unknown field -> gone" posture every other
  kind here has).
- `"consult"` is in `VALID_KINDS` (the gate `office_room_store.append` checks).
- a long (>500 char, PII-laden) answer does NOT leak verbatim through projection — it
  is truncated to the tight `_CONSULT_SUMMARY_CHARS` cap, independent of whatever the
  writer already claims to have trimmed.
"""

from __future__ import annotations

from my_crew.server.office_event_projection import VALID_KINDS, summarize_office_event


def test_consult_is_a_valid_kind():
    assert "consult" in VALID_KINDS


def test_consult_projection_keeps_only_allowlisted_fields():
    body = {
        "from": "agent-a",
        "to": "agent-b",
        "question_summary": "Ưu tiên việc nào?",
        "answer_summary": "Nên làm A trước.",
        "attempt_id": "attempt-123",
        "raw_soul_md": "SHOULD NEVER APPEAR — this is the colleague's persona file",
        "raw_answer": "SHOULD NEVER APPEAR — the unsummarized LLM answer",
    }
    projected = summarize_office_event("consult", body)
    assert projected == {
        "from": "agent-a",
        "to": "agent-b",
        "question_summary": "Ưu tiên việc nào?",
        "answer_summary": "Nên làm A trước.",
        "attempt_id": "attempt-123",
    }
    assert "raw_soul_md" not in projected
    assert "raw_answer" not in projected


def test_consult_projection_truncates_long_pii_laden_answer():
    long_answer = "Bí mật lương của X là 100 triệu. " * 30  # well over 500 chars
    assert len(long_answer) > 500
    body = {
        "from": "agent-a", "to": "agent-b",
        "question_summary": "q", "answer_summary": long_answer,
    }
    projected = summarize_office_event("consult", body)
    # never the raw verbatim text, and capped far tighter than the generic 500-char cap
    assert projected["answer_summary"] != long_answer
    assert len(projected["answer_summary"]) <= 121  # 120 chars + "…"


def test_consult_projection_truncates_long_question_too():
    long_question = "x" * 400
    body = {"from": "a", "to": "b", "question_summary": long_question, "answer_summary": "ok"}
    projected = summarize_office_event("consult", body)
    assert len(projected["question_summary"]) <= 121


def test_consult_projection_missing_fields_default_to_empty_string():
    projected = summarize_office_event("consult", {})
    assert projected == {
        "from": "", "to": "", "question_summary": "", "answer_summary": "", "attempt_id": "",
    }


def test_unknown_kind_still_drops_everything():
    projected = summarize_office_event("not-a-real-kind", {"from": "a", "to": "b"})
    assert projected == {}
