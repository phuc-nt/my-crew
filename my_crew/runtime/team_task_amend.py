"""Full-replan amendment drafts for `team_tasks` (v13 M34) — split out of
`team_task_store.py` to keep that module under the repo's ~200 LOC guideline, same
pattern as `team_task_steps.py`'s split (pure functions over a raw `sqlite3.Connection`,
`TeamTaskStore` delegates).

TOCTOU design:

  - A draft binds `base_plan_hash` = the task's FULL-DAG `plan_hash` AT DRAFT TIME
    (every row, not just the CEO-confirmed subset `_verify_plan_hash` recomputes) —
    this single comparison subsumes every one of: a completed-prefix step finishing
    between draft and confirm, a pending step getting dispatched (reserved -> running)
    in that window, a SECOND amend draft confirming first (amend-over-amend), and a
    ticker-inserted review/rework row landing in that window. ANY of those changes the
    persisted DAG, which changes `plan_hash` (see `task_decomposition
    .decomposition_content_hash` — computed identically over ALL persisted steps here,
    not the `system_inserted=0` subset `_verify_plan_hash` uses, because an amend must
    also catch a NEW review/rework row landing, which the confirmed-only hash would
    blind itself to).
  - SINGLE live draft per task: `set_amendment_draft` terminalizes any prior
    `draft`-status row for the same task before inserting the new one — a CEO who
    re-runs "chỉnh kế hoạch" before confirming the first draft gets exactly one
    confirmable draft, never two racing each other.
  - `confirm_amendment` CONSUMES the draft (status gate: only a row still `draft`
    status can confirm — mirrors `confirm_plan`'s `planning`-only gate) inside ONE
    `BEGIN IMMEDIATE` transaction that ALSO re-validates `base_plan_hash` and swaps the
    pending steps — SQLite's single-writer serialization means this transaction and the
    ticker's own `reserve_step` UPDATE can never interleave mid-operation; whichever
    acquires the RESERVED lock first completes atomically before the other proceeds.
  - Draft TTL: `cleanup_stale_drafts` terminalizes (`status='expired'`) any `draft` row
    older than the caller's TTL — an abandoned draft (CEO asked for a replan, then
    never confirmed/cancelled) must not sit forever as a landmine a much-later,
    unrelated "xác nhận" could accidentally consume.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

#: How long an unconfirmed draft stays confirmable before `cleanup_stale_drafts`
#: terminalizes it — generous enough for a CEO to read a DIFF and reply, short enough
#: that a genuinely abandoned draft does not linger indefinitely.
DEFAULT_DRAFT_TTL_S = 3600

_AMENDMENT_STATUSES = ("draft", "confirmed", "cancelled", "expired", "stale")


@dataclass(frozen=True)
class AmendmentDraft:
    amendment_id: str
    task_id: str
    base_plan_hash: str
    new_plan_hash: str
    new_pending_steps_json: str
    old_pending_step_ids_json: str
    status: str
    created_at: str

    @property
    def new_pending_steps(self) -> list[dict[str, Any]]:
        return json.loads(self.new_pending_steps_json)

    @property
    def old_pending_step_ids(self) -> list[str]:
        return json.loads(self.old_pending_step_ids_json)


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS team_task_amendments ("
        "  amendment_id TEXT PRIMARY KEY,"
        "  task_id TEXT NOT NULL,"
        "  base_plan_hash TEXT NOT NULL,"
        "  new_plan_hash TEXT NOT NULL,"
        "  new_pending_steps_json TEXT NOT NULL,"
        "  old_pending_step_ids_json TEXT NOT NULL DEFAULT '[]',"
        "  status TEXT NOT NULL DEFAULT 'draft',"
        "  created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_team_task_amendments_task "
        "ON team_task_amendments(task_id, status)"
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def set_amendment_draft(
    conn: sqlite3.Connection, task_id: str, *, base_plan_hash: str, new_plan_hash: str,
    new_pending_steps: list[dict[str, Any]], old_pending_step_ids: list[str],
) -> str:
    """Terminalize any prior LIVE (`draft`) row for `task_id`, then insert a fresh one.
    Returns the new `amendment_id`. Caller commits (mirrors every other `_steps`-style
    module in this codebase — the connection owner controls the commit boundary).

    `old_pending_step_ids`: the step_ids that were `pending` AT DRAFT TIME (the set this
    amend intends to replace) — `decomposition_content_hash`/`base_plan_hash` covers
    `step_id`/`title`/`assigned_to`/`deps` but deliberately NOT `status`, so a bare
    `pending -> running` transition on one of these ids between draft and confirm does
    NOT change `base_plan_hash` and would go undetected by that check alone. Recording
    the exact old-pending set here lets `confirm_amendment` verify, at confirm time,
    that every one of these ids is STILL `pending` right before the swap — the narrower
    race `base_plan_hash` alone cannot see (see `team_task_steps.swap_pending_steps`'s
    docstring for the mechanics)."""
    conn.execute(
        "UPDATE team_task_amendments SET status = 'stale' "
        "WHERE task_id = ? AND status = 'draft'",
        (task_id,),
    )
    amendment_id = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO team_task_amendments "
        "(amendment_id, task_id, base_plan_hash, new_plan_hash, new_pending_steps_json, "
        " old_pending_step_ids_json, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'draft', ?)",
        (amendment_id, task_id, base_plan_hash, new_plan_hash,
         json.dumps(new_pending_steps, ensure_ascii=False),
         json.dumps(sorted(old_pending_step_ids), ensure_ascii=False), _now()),
    )
    return amendment_id


def get_draft(conn: sqlite3.Connection, amendment_id: str) -> AmendmentDraft | None:
    row = conn.execute(
        "SELECT amendment_id, task_id, base_plan_hash, new_plan_hash, "
        "new_pending_steps_json, old_pending_step_ids_json, status, created_at "
        "FROM team_task_amendments WHERE amendment_id = ?",
        (amendment_id,),
    ).fetchone()
    if row is None:
        return None
    return AmendmentDraft(*row)


def cancel_amendment_draft(conn: sqlite3.Connection, amendment_id: str) -> bool:
    """CEO "huỷ" at preview time — only a still-`draft` row is cancellable (mirrors
    `cancel_draft`'s plan-level equivalent). Returns True iff a row was updated."""
    cur = conn.execute(
        "UPDATE team_task_amendments SET status = 'cancelled' "
        "WHERE amendment_id = ? AND status = 'draft'",
        (amendment_id,),
    )
    return cur.rowcount > 0


def cleanup_stale_drafts(
    conn: sqlite3.Connection, *, ttl_s: int, now: datetime | None = None,
) -> int:
    """Terminalize (`status='expired'`) every `draft` row older than `ttl_s` seconds.
    Returns the count terminalized. Best-effort hygiene, not correctness-critical —
    `confirm_amendment`'s own `base_plan_hash`/status gates already reject a stale
    confirm even if this never runs; this exists so a truly abandoned draft does not
    sit in `draft` status forever (observability/DB hygiene, not a security boundary).
    """
    cutoff = (now or datetime.now(UTC)) - timedelta(seconds=ttl_s)
    rows = conn.execute(
        "SELECT amendment_id, created_at FROM team_task_amendments WHERE status = 'draft'"
    ).fetchall()
    expired_ids = []
    for amendment_id, created_at in rows:
        try:
            created = datetime.fromisoformat(created_at)
        except ValueError:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if created < cutoff:
            expired_ids.append(amendment_id)
    for amendment_id in expired_ids:
        conn.execute(
            "UPDATE team_task_amendments SET status = 'expired' "
            "WHERE amendment_id = ? AND status = 'draft'",
            (amendment_id,),
        )
    return len(expired_ids)


@dataclass(frozen=True)
class ConfirmAmendmentResult:
    """Outcome of `confirm_amendment` — never raises for an ordinary TOCTOU loss (a
    stale hash / a just-reserved step is an expected race, not a bug); `ok=False`
    always carries a `reason` the ops-command layer turns into a CEO-facing reply."""

    ok: bool
    reason: str = ""
    skipped_step_ids: tuple[str, ...] = ()


def full_dag_plan_hash(steps: Any) -> str:
    """Full-DAG content hash over EVERY persisted step row (unlike
    `coordinator_graph._verify_plan_hash`, which recomputes over the `system_inserted=0`
    CONFIRMED subset only) — an amend's `base_plan_hash` must catch a NEW review/rework
    row landing between draft and confirm too, so it deliberately hashes everything.

    Public (not `_`-prefixed): `ops_adjust_team_task.preview_adjust_team_task` calls this
    directly (via `TeamTaskStore.get(task_id).steps`) to compute `base_plan_hash` at draft
    time — `confirm_amendment` below recomputes the SAME thing at confirm time from the
    connection it already holds inside its `BEGIN IMMEDIATE` transaction.
    """
    from my_crew.agent.task_decomposition import decomposition_content_hash

    return decomposition_content_hash(SimpleNamespace(steps=list(steps)))


def confirm_amendment(
    conn: sqlite3.Connection, task_id: str, amendment_id: str,
) -> ConfirmAmendmentResult:
    """The one `BEGIN IMMEDIATE` transaction that re-validates + swaps + binds + consumes
    a draft — see module docstring for the TOCTOU rationale. Commits on success, rolls
    back on any rejection (leaving the draft `draft`-status and the DAG untouched, so a
    rejected confirm is always safely re-previewable).

    SQLite single-writer serialization is the actual concurrency primitive here: `BEGIN
    IMMEDIATE` blocks until it can acquire the RESERVED write lock, so this whole
    function body executes with NO other writer (the ticker's `reserve_step`, another
    confirm, a fresh draft) able to touch `team_steps`/`team_task_amendments` until
    COMMIT — the `base_plan_hash` re-read below is therefore guaranteed fresh as of the
    instant this transaction started, not a snapshot that could go stale mid-function.
    """
    from my_crew.runtime import team_task_steps as _steps

    conn.execute("BEGIN IMMEDIATE")
    try:
        draft = get_draft(conn, amendment_id)
        if draft is None or draft.task_id != task_id:
            conn.rollback()
            return ConfirmAmendmentResult(ok=False, reason="amendment_not_found")
        if draft.status != "draft":
            # Consumed already (confirmed/cancelled by an earlier call), superseded by
            # a newer draft (`set_amendment_draft` marked it 'stale'), or TTL-expired —
            # every non-'draft' status means "not confirmable anymore", same message.
            conn.rollback()
            return ConfirmAmendmentResult(ok=False, reason="amendment_not_live")

        current_steps = _steps.steps_for_task(conn, task_id)
        current_hash = full_dag_plan_hash(current_steps)
        if current_hash != draft.base_plan_hash:
            conn.rollback()
            return ConfirmAmendmentResult(ok=False, reason="plan_changed_since_draft")

        skipped = _steps.swap_pending_steps(
            conn, task_id, draft.new_pending_steps,
            expected_pending_step_ids=draft.old_pending_step_ids,
        )
        if skipped:
            # A pending step this draft meant to replace got reserved->running in the
            # instant between the hash check above and the swap (a window `BEGIN
            # IMMEDIATE` cannot close any further — the ticker's reserve happened
            # BEFORE this transaction even started, just after the hash was last
            # legitimately verified). Reject rather than partially apply: the CEO must
            # re-preview against the NOW-current DAG (which includes the step that just
            # started running), never silently apply a plan that no longer accounts
            # for it.
            conn.rollback()
            return ConfirmAmendmentResult(
                ok=False, reason="pending_step_just_reserved", skipped_step_ids=tuple(skipped),
            )

        conn.execute(
            "UPDATE team_tasks SET plan_hash = ? WHERE id = ?", (draft.new_plan_hash, task_id),
        )
        conn.execute(
            "UPDATE team_task_amendments SET status = 'confirmed' WHERE amendment_id = ?",
            (amendment_id,),
        )
        conn.commit()
        return ConfirmAmendmentResult(ok=True)
    except Exception:
        conn.rollback()
        raise
