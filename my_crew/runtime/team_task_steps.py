"""Step-level SQL for the team-task store — split out of `team_task_store.py`
to keep each module under the repo's ~200 LOC guideline.

Pure functions over a raw `sqlite3.Connection` (no class): `TeamTaskStore` owns the
connection/schema/task-level API and delegates every `team_steps` row operation here.
Kept function-style (not a second class) because every call already takes the shared
connection as its first argument — a class would add no encapsulation, only ceremony.

Lease semantics (mirrors the store's docstring): `reserve_step` always claims (issues a
fresh `attempt_id`, marks `running`); the caller decides whether re-reserving an already-
`running` step is legitimate via `lease_expired` (lease-clock check only — the artifact-
absence half of the double-spawn guard is owned by the coordinator ticker, since only it
knows the artifact path convention).

Heartbeat owner: the WORKER refreshes `last_seen`/`lease_expires_at` at each of its own
graph node boundaries (perceive/work/deliver — see `team_step_runner.run_team_step`), so
a long-running-but-alive step's lease never goes stale mid-work. The ticker still kills
the pid and marks `timeout` unconditionally once a lease IS expired (it does not probe
"is the heartbeat merely late" — a missed heartbeat past the TTL is itself the timeout
signal), so double-spawn is prevented two ways: normally the heartbeat keeps the lease
alive so expiry never fires on live work; if it ever did anyway (e.g. a heartbeat write
lost a race), `set_step_status`'s optional `attempt_id` guard makes the ORIGINAL worker's
terminal write (`mark_done`/`mark_failed`) a no-op against the new attempt's row.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

STEP_STATUSES = ("pending", "running", "awaiting_approval", "waiting_clarify", "done",
                 "failed", "timeout")


@dataclass(frozen=True)
class TeamStep:
    task_id: str
    step_id: str
    seq: int
    title: str
    assigned_to: str
    deps: tuple[str, ...]
    status: str
    outcome_ref: str | None
    cost_usd: float | None
    attempt_id: str | None
    child_pid: int | None
    spawned_at: str | None
    last_seen: str | None
    lease_expires_at: str | None
    escalated_at: str | None
    # Set only when `deliver` gated this step's external write behind a Lớp B approval
    # (`ActionGateway`'s own `GatewayResult.approval_id`) — the correlation key the
    # ticker needs to poll `ApprovalStore` and resume the step once a human decides.
    # None for every step that never hit an external-write gate (the overwhelming
    # majority — an internal-only step has nothing to approve).
    approval_id: int | None
    # Self-check acceptance criteria (free text, default "") — per-step METADATA the
    # step graph's `self_check` node reads as its rubric. NOT part of
    # `decomposition_content_hash` (see `task_decomposition.decomposition_content_hash`'s
    # docstring) — purely a round-trip field from decompose -> store -> self_check.
    acceptance: str
    # --- P2 peer-review columns (all additive, migrate-free) ---
    # "work" (a normal content step) | "review" (ticker-inserted peer soát) |
    # "rework" (ticker-inserted fix-up after a "needs_rework" verdict). Confirmed steps
    # are always "work"; review/rework rows are minted ONLY by the ticker rule
    # (`coordinator_nodes.tick_actions`), never by the decompose LLM.
    step_type: str
    # True (content steps only, LLM-set + code-validated) iff this step's completion
    # should trigger the ticker's review-insert rule. review/rework steps are never
    # `needs_review` themselves (would loop forever reviewing a review).
    needs_review: bool
    # True iff this row was minted by the ticker rule (review/rework), not by the
    # CEO-confirmed decompose. Read by `coordinator_graph._verify_plan_hash` to EXCLUDE
    # this row from the confirmed-DAG hash recompute (Decision A).
    system_inserted: bool
    # For a review/rework row: the content step_id it was inserted for. None on a
    # normal "work" row.
    parent_step_id: str | None
    # For a review row: which review round this is (0-indexed, capped at 2 rounds —
    # see `tick_actions`'s review-insert rule). 0 on every non-review row.
    review_round: int
    # v34 P2: the ClarifyStore row this step paused on (status "waiting_clarify") —
    # the correlation key the ticker polls to resume once the CEO answers/expires.
    # None on every step that never interrupted on a CEO question.
    clarify_id: int | None = None
    # v45 tier-0 routing: True iff the step must run real shell/code → escalates to the deep_agent
    # Docker sandbox; False (default) → runs on the fast, Docker-free create_agent tier. Read by
    # `resolve_step_runtime` (v45) + bound into `decomposition_content_hash` (conditionally, only
    # when True) so the CEO's confirm covers the step's shell posture. Defaulted (not positional)
    # so pre-v45 `TeamStep(...)` constructions and fixtures stay valid.
    needs_shell: bool = False
    # v34 P4: JSON list [{"title","assigned_to"}] the step proposed instead of doing
    # the work itself ("Đã chia bước"). Set at mark_done; the ticker's fanout-insert
    # rule reads it, mints the sub/gather rows, and the children's existence is the
    # idempotency guard. None on every step that never proposed a split.
    split_proposal_json: str | None = None


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS team_steps ("
        "  seq INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  task_id TEXT NOT NULL,"
        "  step_id TEXT NOT NULL,"
        "  title TEXT NOT NULL DEFAULT '',"
        "  assigned_to TEXT NOT NULL DEFAULT '',"
        "  deps_json TEXT NOT NULL DEFAULT '[]',"
        "  status TEXT NOT NULL DEFAULT 'pending',"
        "  outcome_ref TEXT,"
        "  cost_usd REAL,"
        "  attempt_id TEXT,"
        "  child_pid INTEGER,"
        "  spawned_at TEXT,"
        "  last_seen TEXT,"
        "  lease_expires_at TEXT,"
        "  escalated_at TEXT,"
        "  approval_id INTEGER,"
        "  UNIQUE(task_id, step_id)"
        ")"
    )
    # Additive column for a store created before this field existed — `ALTER TABLE`
    # is a no-op (caught + ignored) once the column is already present, matching the
    # rest of this codebase's migration-free "CREATE TABLE IF NOT EXISTS" posture for
    # a single-tenant local SQLite file.
    try:
        conn.execute("ALTER TABLE team_steps ADD COLUMN approval_id INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE team_steps ADD COLUMN acceptance TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE team_steps ADD COLUMN clarify_id INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE team_steps ADD COLUMN split_proposal_json TEXT")
    except sqlite3.OperationalError:
        pass
    # P2 peer-review columns — same migrate-free ALTER pattern. Defaults reproduce v12
    # behavior exactly (step_type='work', needs_review=0, system_inserted=0) so a store
    # created before this phase existed round-trips its old rows unchanged.
    for ddl in (
        "ALTER TABLE team_steps ADD COLUMN step_type TEXT NOT NULL DEFAULT 'work'",
        "ALTER TABLE team_steps ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE team_steps ADD COLUMN system_inserted INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE team_steps ADD COLUMN parent_step_id TEXT",
        "ALTER TABLE team_steps ADD COLUMN review_round INTEGER NOT NULL DEFAULT 0",
        # v45 tier-0 routing: default 0 reproduces pre-v45 behavior (no-shell → create_agent)
        # and, because `decomposition_content_hash` emits needs_shell only when True, an old
        # row (all 0) hashes byte-identical to before — no plan-hash-mismatch stall on migrate.
        "ALTER TABLE team_steps ADD COLUMN needs_shell INTEGER NOT NULL DEFAULT 0",
    ):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_step(data: dict[str, Any]) -> TeamStep:
    try:
        deps = tuple(json.loads(data["deps_json"]))
    except (json.JSONDecodeError, TypeError):
        deps = ()
    return TeamStep(
        task_id=data["task_id"], step_id=data["step_id"], seq=int(data["seq"]),
        title=data["title"], assigned_to=data["assigned_to"], deps=deps,
        status=data["status"], outcome_ref=data["outcome_ref"],
        cost_usd=data["cost_usd"], attempt_id=data["attempt_id"],
        child_pid=data["child_pid"], spawned_at=data["spawned_at"],
        last_seen=data["last_seen"], lease_expires_at=data["lease_expires_at"],
        escalated_at=data["escalated_at"], approval_id=data.get("approval_id"),
        acceptance=data.get("acceptance") or "",
        # P2: stored as SQLite INTEGER (0/1) — coerce explicitly to `bool` here so
        # callers never need to know the on-disk representation. `acceptance`/`step_type`/
        # `needs_review` do NOT enter `decomposition_content_hash`; `needs_shell` (v45) DOES
        # (conditionally, only when True), so its int->bool round-trip must be exact — it is.
        step_type=data.get("step_type") or "work",
        needs_review=bool(int(data.get("needs_review") or 0)),
        needs_shell=bool(int(data.get("needs_shell") or 0)),
        system_inserted=bool(int(data.get("system_inserted") or 0)),
        parent_step_id=data.get("parent_step_id"),
        review_round=int(data.get("review_round") or 0),
        clarify_id=data.get("clarify_id"),
        split_proposal_json=data.get("split_proposal_json"),
    )


def _cols(conn: sqlite3.Connection) -> list[str]:
    return [d[0] for d in conn.execute("SELECT * FROM team_steps LIMIT 0").description]


def replace_steps(conn: sqlite3.Connection, task_id: str, steps: list[dict[str, Any]]) -> None:
    """Delete any existing steps for `task_id` and insert the confirmed DAG (used by
    `set_plan`); insertion order becomes the stable AUTOINCREMENT `seq`.

    Every row inserted here is, by definition, part of the CEO-CONFIRMED DAG —
    `system_inserted` is always 0 (only `insert_step`, called by the ticker rule AFTER
    confirm, ever sets it to 1). `step_type`/`needs_review` come from the caller's dict
    (the decompose LLM's proposal, already code-validated by `task_decomposition
    .validate_decomposition`) with the v12-compatible defaults `"work"`/`False` when
    absent, so a caller that never sets these keys (every pre-P2 test/fixture) persists
    rows byte-identical to before this phase existed.
    """
    conn.execute("DELETE FROM team_steps WHERE task_id = ?", (task_id,))
    for step in steps:
        conn.execute(
            "INSERT INTO team_steps "
            "(task_id, step_id, title, assigned_to, deps_json, status, acceptance, "
            " step_type, needs_review, needs_shell, system_inserted) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, 0)",
            (
                task_id, step["step_id"], step.get("title", ""), step.get("assigned_to", ""),
                json.dumps(list(step.get("deps", ())), ensure_ascii=False),
                step.get("acceptance", ""),
                step.get("step_type") or "work",
                1 if step.get("needs_review") else 0,
                1 if step.get("needs_shell") else 0,  # v45: default 0 (no-shell → create_agent)
            ),
        )


def insert_step(conn: sqlite3.Connection, task_id: str, step: dict[str, Any], *,
                needs_review: bool = False) -> None:
    """Append ONE dynamically-minted row (review/rework) AFTER the task's confirmed DAG
    is already open — the AUTOINCREMENT `seq` continues from wherever it left off, so
    this row always sorts after every existing step in `steps_for_task`/`next_pending_step`.

    `system_inserted=1` is ALWAYS forced here, and `needs_review` is NEVER read off the
    caller's dict (Finding fail-F: a caller must never accidentally copy
    `needs_review=True` from the REVIEWED step onto a new review/rework row, which
    would make the ticker review-the-review forever). It IS settable via the explicit
    keyword-only parameter — v34 P4's GATHER row consciously inherits its parent's
    flag so the merged output gets the quality gate the parent would have had. `step` must carry
    `step_id`/`title`/`assigned_to`/`deps`/`step_type`/`parent_step_id`/`review_round`;
    `acceptance` defaults to "" (a review/rework row has no self-check rubric of its
    own — its rubric IS the parent content step's `acceptance`, read directly by
    `review_graph.py`). v45 `needs_shell` is deliberately NOT settable here: these
    ticker-minted rows (review/rework/gather) are system_inserted, excluded from the confirm
    hash, and their text-only work never needs a shell — they take the schema DEFAULT 0 →
    create_agent tier, matching the `needs_review`-not-copied guard-rail above.
    """
    conn.execute(
        "INSERT INTO team_steps "
        "(task_id, step_id, title, assigned_to, deps_json, status, acceptance, "
        " step_type, needs_review, system_inserted, parent_step_id, review_round) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, 1, ?, ?)",
        (
            task_id, step["step_id"], step.get("title", ""), step.get("assigned_to", ""),
            json.dumps(list(step.get("deps", ())), ensure_ascii=False),
            step.get("acceptance", ""),
            step.get("step_type") or "review",
            int(bool(needs_review)),
            step.get("parent_step_id"),
            int(step.get("review_round") or 0),
        ),
    )


def clear_split_proposal(conn: sqlite3.Connection, task_id: str, step_id: str) -> None:
    """NULL one step's split_proposal_json (see `TeamTaskStore.consume_split_proposal`)."""
    conn.execute(
        "UPDATE team_steps SET split_proposal_json = NULL "
        "WHERE task_id = ? AND step_id = ?", (task_id, step_id),
    )


def steps_for_task(conn: sqlite3.Connection, task_id: str) -> tuple[TeamStep, ...]:
    rows = conn.execute(
        "SELECT * FROM team_steps WHERE task_id = ? ORDER BY seq", (task_id,)
    ).fetchall()
    cols = _cols(conn)
    return tuple(_row_to_step(dict(zip(cols, r, strict=True))) for r in rows)


def get_step_row(conn: sqlite3.Connection, task_id: str, step_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM team_steps WHERE task_id = ? AND step_id = ?", (task_id, step_id),
    ).fetchone()
    if row is None:
        return None
    return dict(zip(_cols(conn), row, strict=True))


def get_step(conn: sqlite3.Connection, task_id: str, step_id: str) -> TeamStep | None:
    data = get_step_row(conn, task_id, step_id)
    return _row_to_step(data) if data is not None else None


def next_pending_step(conn: sqlite3.Connection, task_id: str) -> TeamStep | None:
    """Lowest-`seq` `pending` step whose deps are ALL `done` — None if nothing is ready."""
    steps = steps_for_task(conn, task_id)
    done_ids = {s.step_id for s in steps if s.status == "done"}
    for step in steps:  # already ordered by seq
        if step.status == "pending" and all(dep in done_ids for dep in step.deps):
            return step
    return None


def reserve_step(conn: sqlite3.Connection, task_id: str, step_id: str, *, lease_ttl_s: int) -> str:
    """Claim a fresh spawn attempt: new `attempt_id`, `running`, lease clock reset.

    Always claims — the caller (ticker) must decide beforehand whether re-reserving an
    already-`running` step is legitimate (lease expired AND outcome artifact absent).

    Raises `ValueError` if `(task_id, step_id)` does not exist: a lease minted for a row
    that was never planned (typo, stale task) can never be verified by anyone, so a
    silent "successful" reserve here would only surface as a confusing later failure —
    fail loud at the point of the actual mistake instead.
    """
    attempt_id = uuid.uuid4().hex
    now = _now()
    expires = (datetime.now(UTC) + timedelta(seconds=lease_ttl_s)).isoformat()
    # `approval_id = NULL`: a fresh attempt starts with no pending gate of its own — a
    # stale id from a PRIOR attempt (e.g. this reserve is the resume-after-approval
    # re-run) must never be read by the next `awaiting_approval` poll as if it still
    # applied to the new attempt.
    cur = conn.execute(
        "UPDATE team_steps SET status = 'running', attempt_id = ?, spawned_at = ?, "
        "last_seen = ?, lease_expires_at = ?, approval_id = NULL, clarify_id = NULL, "
        "split_proposal_json = NULL "
        "WHERE task_id = ? AND step_id = ?",
        (attempt_id, now, now, expires, task_id, step_id),
    )
    if cur.rowcount == 0:
        raise ValueError(f"cannot reserve unknown team step ({task_id!r}, {step_id!r})")
    return attempt_id


def lease_expired(conn: sqlite3.Connection, task_id: str, step_id: str, *,
                   now: datetime | None = None) -> bool:
    """True when the lease is missing or its expiry is in the past (or the step
    itself does not exist — treated as expired/reservable)."""
    data = get_step_row(conn, task_id, step_id)
    if data is None:
        return True
    expires_raw = data.get("lease_expires_at")
    if not expires_raw:
        return True
    try:
        expires = datetime.fromisoformat(expires_raw)
    except ValueError:
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) >= expires


def verify_attempt(conn: sqlite3.Connection, task_id: str, step_id: str, attempt_id: str) -> bool:
    """True iff the step is `running` with EXACTLY this `attempt_id`."""
    data = get_step_row(conn, task_id, step_id)
    if data is None:
        return False
    return data.get("status") == "running" and data.get("attempt_id") == attempt_id


def record_spawn(conn: sqlite3.Connection, task_id: str, step_id: str, pid: int) -> None:
    conn.execute(
        "UPDATE team_steps SET child_pid = ?, last_seen = ? WHERE task_id = ? AND step_id = ?",
        (pid, _now(), task_id, step_id),
    )


def heartbeat(conn: sqlite3.Connection, task_id: str, step_id: str, *, lease_ttl_s: int) -> None:
    expires = (datetime.now(UTC) + timedelta(seconds=lease_ttl_s)).isoformat()
    conn.execute(
        "UPDATE team_steps SET last_seen = ?, lease_expires_at = ? "
        "WHERE task_id = ? AND step_id = ?",
        (_now(), expires, task_id, step_id),
    )


def set_step_status(
    conn: sqlite3.Connection, task_id: str, step_id: str, status: str, *,
    outcome_ref: str | None = None, cost_usd: float | None = None,
    attempt_id: str | None = None, approval_id: int | None = None,
    clarify_id: int | None = None, split_proposal_json: str | None = None,
) -> bool:
    """Write a step's status (+ optionally its outcome/cost/approval_id). Returns True
    iff a row was actually updated.

    `attempt_id`, when given, guards the write: it only applies `WHERE ... AND
    attempt_id = ?`, so a worker whose lease was re-reserved out from under it (e.g. the
    ticker killed it for a timeout, or legitimately re-reserved it after the lease
    expired) writes a no-op instead of clobbering the NEW attempt's row or double-
    counting cost against the task. Terminal writes from `run_team_step`
    (`mark_done`/`mark_failed`) always pass their own `attempt_id`. The ticker's own
    terminal writes (`mark_failed` on retries-exhausted/rejection, `mark_timeout` on
    lease expiry) pass the `attempt_id` it read the step's row under (`step.attempt_id`
    off its own snapshot), same guard against a concurrent re-reservation racing the
    ticker's write. `mark_awaiting_approval` is called only by the worker process
    itself (`team_step_runner.py`), which always holds and passes its own `attempt_id`
    — the ticker never calls it directly (resuming a step it approved is a fresh
    reserve+spawn, not a status write on the paused row).

    `approval_id`, when given, is stashed on the row so the ticker can later poll
    `ApprovalStore` for this step's decision (see `coordinator_nodes.tick_actions
    .poll_awaiting_approval_step`) — only ever set alongside `status="awaiting_approval"`.
    """
    if status not in STEP_STATUSES:
        raise ValueError(f"invalid team step status {status!r}; expected one of {STEP_STATUSES}")
    where = "WHERE task_id = ? AND step_id = ?"
    params: tuple[Any, ...] = (task_id, step_id)
    if attempt_id is not None:
        where += " AND attempt_id = ?"
        params = (*params, attempt_id)
    if outcome_ref is not None or cost_usd is not None or approval_id is not None \
            or clarify_id is not None or split_proposal_json is not None:
        cur = conn.execute(
            "UPDATE team_steps SET status = ?, "
            "outcome_ref = COALESCE(?, outcome_ref), "
            "cost_usd = COALESCE(?, cost_usd), "
            "approval_id = COALESCE(?, approval_id), "
            "clarify_id = COALESCE(?, clarify_id), "
            "split_proposal_json = COALESCE(?, split_proposal_json) " + where,
            (status, outcome_ref, cost_usd, approval_id, clarify_id,
             split_proposal_json, *params),
        )
    else:
        cur = conn.execute("UPDATE team_steps SET status = ? " + where, (status, *params))
    updated = cur.rowcount > 0
    if updated and cost_usd is not None:
        conn.execute(
            "UPDATE team_tasks SET cost_usd_total = cost_usd_total + ? WHERE id = ?",
            (cost_usd, task_id),
        )
    return updated


def append_outcome(conn: sqlite3.Connection, task_id: str, step_id: str, outcome_ref: str) -> None:
    conn.execute(
        "UPDATE team_steps SET outcome_ref = ? WHERE task_id = ? AND step_id = ?",
        (outcome_ref, task_id, step_id),
    )


def swap_pending_steps(
    conn: sqlite3.Connection, task_id: str, new_pending: list[dict[str, Any]], *,
    expected_pending_step_ids: list[str],
) -> list[str]:
    """Full-replan swap (v13 M34): DELETE every row in `expected_pending_step_ids`
    (the step_ids that were `pending` AT DRAFT TIME) and INSERT `new_pending` in its
    place — `done`/`running`/`failed`/`timeout`/`awaiting_approval` rows are NEVER
    touched (Decision: amend only ever replaces the not-yet-started tail of the DAG).

    Caller contract: MUST run this inside the SAME transaction as the `base_plan_hash`
    re-validate (`team_task_amend.confirm_amendment`'s `BEGIN IMMEDIATE`) — this
    function itself does not commit, so the caller controls the transaction boundary.

    Skip-just-reserved race: between the CEO's draft preview and this confirm call, the
    ticker may have ALREADY reserved one of the very steps this swap is about to delete
    (`reserve_step` flips it `pending` -> `running` — a completely independent write
    path this function has no lock over outside the caller's own `BEGIN IMMEDIATE`).
    This race does NOT change `decomposition_content_hash`/`base_plan_hash` (that hash
    deliberately excludes `status` — see `task_decomposition.decomposition_content_hash`'s
    docstring), so the hash check alone cannot catch it; `expected_pending_step_ids`
    (the draft's own snapshot of what was pending when it was created) is the
    structural check that does. Deletes ONLY rows that are STILL `pending` right now
    (re-read fresh, not the caller's possibly-stale in-memory snapshot) — deleting a
    step a worker may already be running against would orphan that running process's
    row out from under it. Returns the list of `expected_pending_step_ids` that were
    NOT still `pending` (i.e. raced away); a non-empty return means the caller must
    reject the confirm and ask the CEO to re-preview (the DAG moved between draft and
    confirm).
    """
    rows = conn.execute(
        "SELECT step_id, status FROM team_steps WHERE task_id = ?", (task_id,)
    ).fetchall()
    current_status = {step_id: status for step_id, status in rows}
    # `BEGIN IMMEDIATE` (the caller's transaction) already holds a RESERVED write lock
    # for this whole call, so this SELECT's snapshot cannot go stale between here and
    # the per-row DELETE below — no other connection can write to `team_steps` until
    # this transaction commits/rolls back. The per-row `AND status = 'pending'` guard on
    # the DELETE is defense-in-depth (matches this codebase's `attempt_id`-guarded
    # UPDATE convention in `set_step_status` of never trusting a bare SELECT snapshot
    # alone), not the primary correctness mechanism — SQLite's txn isolation is.
    skipped: list[str] = []
    for step_id in expected_pending_step_ids:
        if current_status.get(step_id) != "pending":
            # No longer pending (raced to running, or vanished) — do not delete it, and
            # report it so the caller rejects this confirm outright.
            skipped.append(step_id)
            continue
        cur = conn.execute(
            "DELETE FROM team_steps WHERE task_id = ? AND step_id = ? AND status = 'pending'",
            (task_id, step_id),
        )
        if cur.rowcount == 0:
            skipped.append(step_id)
    if skipped:
        # A partial swap would leave the DAG in a state neither the old nor the new
        # plan describes — the caller (inside its own BEGIN IMMEDIATE) is expected to
        # roll back the whole transaction on a non-empty return, so no INSERT happens
        # here either; nothing has been committed by the caller yet at this point.
        return sorted(skipped)
    for step in new_pending:
        conn.execute(
            "INSERT INTO team_steps "
            "(task_id, step_id, title, assigned_to, deps_json, status, acceptance, "
            " step_type, needs_review, needs_shell, system_inserted) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, 0)",
            (
                task_id, step["step_id"], step.get("title", ""), step.get("assigned_to", ""),
                json.dumps(list(step.get("deps", ())), ensure_ascii=False),
                step.get("acceptance", ""),
                step.get("step_type") or "work",
                1 if step.get("needs_review") else 0,
                1 if step.get("needs_shell") else 0,  # v45 tier-0 routing
            ),
        )
    return []
