"""Office room event projection — the PII firewall for `office_room_store` (v12 M29).

Same philosophy as `sse_events.summarize_node` (`my_crew/server/sse_events.py:17`): project
a raw event body down to an ALLOWLIST of non-PII fields per `kind`. Anything not on the
allowlist is DROPPED. Unknown kind -> {} (drop all — a safe default if the room grows a
new kind before this module is updated).

Applied AT WRITE TIME by `office_room_store.append` (workers are the writers), NOT at
SSE emit time — so the store itself never holds an unprojected field, and replay (a late
subscriber reading old rows back out of the store) is automatically as safe as the live
stream. Free-form `body_json` passthrough is forbidden by construction: every kind here
lists its own short, explicit set of string/number fields.
"""

from __future__ import annotations

#: Max length for any free-text field this module keeps — a room message is a short
#: timeline line, not a report viewer; long text is truncated with an explicit marker
#: instead of silently keeping (and thus risking widening) a large payload.
_MAX_TEXT_CHARS = 500

#: Much tighter cap for `consult`'s summary fields (M33) — the writer
#: (`team_task_consult.ask_colleague`) already trims to ~120 chars before this ever
#: runs, but the projection layer is the actual write-time firewall (same posture as
#: every other kind here): it must enforce its OWN cap independent of what the
#: upstream caller claims to have already done, so a future writer that skips the
#: writer-side trim still cannot push a long (potentially PII-laden) answer verbatim
#: into the room store.
_CONSULT_SUMMARY_CHARS = 120


def _short(value: object) -> str:
    text = str(value or "")
    if len(text) > _MAX_TEXT_CHARS:
        return text[:_MAX_TEXT_CHARS] + "…"
    return text


def _short_consult(value: object) -> str:
    text = str(value or "")
    if len(text) > _CONSULT_SUMMARY_CHARS:
        return text[:_CONSULT_SUMMARY_CHARS] + "…"
    return text


#: `review`'s `verdict` field is a closed enum (never free text) — a value outside this
#: set is dropped entirely rather than passed through, same "unknown -> drop" posture as
#: an unrecognized `kind`.
_REVIEW_VERDICTS = frozenset({"passed", "needs_rework"})

#: `step_status`'s `phase` field is likewise a closed enum — the exact 4 tags the step
#: graph's `get_stream_writer()` calls emit (`team_task_graph.PHASE_WORK/
#: PHASE_SELF_CHECK/PHASE_REWORK/PHASE_RECOVER`). A value outside this set is dropped
#: (empty string) rather than passed through truncated — same "unknown -> drop" posture
#: as `verdict` above, not just a length cap.
_STEP_PHASES = frozenset({"dang-lam", "tu-soat", "dang-sua", "nho-tro-giup"})


def summarize_office_event(kind: str, body: dict) -> dict:
    """Project a raw office-event body to its non-PII allowlist (drop everything else).

    `kind` one of ceo | assignment | step_status | handoff | milestone | consult | review.
    Unknown kind -> {} (drop all).
    """
    if kind == "ceo":
        return {"text": _short(body.get("text"))}
    if kind == "assignment":
        return {
            "task_title": _short(body.get("task_title")),
            "step_count": int(body.get("step_count") or 0),
            "summary": _short(body.get("summary")),
            # v15 PIC: `pic` is an internal agent id (same non-PII category as
            # `step_status.assigned_to`); `task_id` is the same opaque internal id
            # `milestone` already carries — together they let the FE badge the PIC's
            # desk and clear it on this task's `milestone: done` event.
            "pic": _short(body.get("pic")),
            "task_id": _short(body.get("task_id")),
        }
    if kind == "step_status":
        phase = _short(body.get("phase"))
        projected = {
            "task_title": _short(body.get("task_title")),
            "step_title": _short(body.get("step_title")),
            "status": _short(body.get("status")),
            "assigned_to": _short(body.get("assigned_to")),
            # `phase` is a closed-set tag the step graph emits mid-run (see
            # `team_task_graph.PHASE_WORK/PHASE_SELF_CHECK/PHASE_REWORK`) — not free
            # text, so it is value-checked against `_STEP_PHASES` (dropped to "" if
            # unrecognized) rather than merely length-capped, same posture as
            # `review`'s `verdict` above. `attempt_id` is an internal opaque UUID
            # (same non-PII category as `milestone`'s `task_id` above) — the FE uses
            # it to drop a stale/zombie attempt's phase events.
            "phase": phase if phase in _STEP_PHASES else "",
            "attempt_id": _short(body.get("attempt_id")),
        }
        # v54: pass through the deep_team flag ONLY when true — omitted (not even a
        # `False` key) when the runtime did not opt in, keeping pre-v54 events byte-
        # identical and the room feed lean (see `team_step_runner._append_step_phase_event`).
        if body.get("deep_team"):
            projected["deep_team"] = True
        return projected
    if kind == "handoff":
        return {
            "task_title": _short(body.get("task_title")),
            "step_title": _short(body.get("step_title")),
            "message": _short(body.get("message")),
            "assigned_to": _short(body.get("assigned_to")),
        }
    if kind == "milestone":
        return {
            # `task_id` (not PII — an internal opaque id, same shape as the room_id
            # itself) rides alongside `task_title` so a dedup/identity key built from
            # this projected body never depends on a human-editable title: two tasks
            # given the same brief text would otherwise collide in `milestone_mirror_runner`'s
            # per-(task, milestone, day) dedup claim.
            "task_id": _short(body.get("task_id")),
            "task_title": _short(body.get("task_title")),
            "milestone": _short(body.get("milestone")),
            "message": _short(body.get("message")),
        }
    if kind == "consult":
        # M33 role-play consultation (see `team_task_consult.ask_colleague`'s module
        # docstring): `from`/`to` are internal agent ids (non-PII, same category as
        # `assigned_to` above). `question_summary`/`answer_summary` are the ONLY two
        # free-text fields — capped at `_CONSULT_SUMMARY_CHARS`, never the raw SOUL.md/
        # PROJECT.md content or the raw LLM answer (the writer already trims to the
        # same ~120 chars; this is the write-time re-enforcement, not a trust of that).
        return {
            "from": _short(body.get("from")),
            "to": _short(body.get("to")),
            "question_summary": _short_consult(body.get("question_summary")),
            "answer_summary": _short_consult(body.get("answer_summary")),
            # opaque internal UUID, same non-PII category as `step_status.attempt_id`.
            "attempt_id": _short(body.get("attempt_id")),
        }
    if kind == "external_action":
        # v54: Action Gateway outcome bridge — every mutation that passes through
        # `ActionGateway._record` mirrors here. No-content-echo (same posture as every
        # other kind): `tool`/`detail` are a short label + target id (channel/issue-key/
        # recipient), never the action's args/message body. `outcome` is the gateway's own
        # verdict string ("allow"/"deny"/"pending"/"dry_run"/"skipped"/"reject").
        return {
            "actor": _short(body.get("actor")),
            "tool": _short(body.get("tool")),
            "action_type": _short(body.get("action_type")),
            "outcome": _short(body.get("outcome")),
            "detail": _short(body.get("detail")),
        }
    if kind == "review":
        # M32 peer review verdict (see `review_graph.run_review_step`): `verdict` is a
        # closed enum, never the model's raw JSON; `failure_count` is a count, never the
        # failure LIST itself (each failure string could echo back reviewed content) —
        # the room only ever shows "N lỗi", the failure detail stays in the verdict
        # artifact + the rework step's own handoff, both internal-only.
        verdict = _short(body.get("verdict"))
        return {
            "task_title": _short(body.get("task_title")),
            "step_title": _short(body.get("step_title")),
            "verdict": verdict if verdict in _REVIEW_VERDICTS else "",
            "failure_count": int(body.get("failure_count") or 0),
            # v34 P5: per-criterion COUNTS (ints, same no-content-echo category as
            # failure_count) — 0/absent for any pre-P5 event.
            "criteria_total": int(body.get("criteria_total") or 0),
            "criteria_passed": int(body.get("criteria_passed") or 0),
            "assigned_to": _short(body.get("assigned_to")),
        }
    return {}


#: The only valid `kind` values a caller may append — `office_room_store.append` uses
#: this to fail loud on a typo'd kind instead of silently persisting an ungoverned event.
VALID_KINDS = frozenset(
    {
        "ceo", "assignment", "step_status", "handoff", "milestone", "consult", "review",
        "external_action",  # v54: Action Gateway outcome bridge
    }
)
