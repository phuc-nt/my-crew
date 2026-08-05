"""Digest builder for the secretary heartbeat (v68) — pure code, never an LLM.

The heartbeat's whole product promise is "silent unless something genuinely needs the
CEO". That promise is only affordable because this module answers "is there anything?"
with SQL instead of a model call: an empty digest costs zero tokens, so a quiet system
is free to check every 30 minutes forever.

Every signal here is read from a column that actually exists. Five signals, chosen
because each one means a human has to do something:

1. `stalled` team tasks — the ticker could not proceed on its own.
2. `done` tasks whose summary never reached the room AND whose delivery-retry sweep has
   already given up (`delivery_attempts >= MAX_DELIVERY_ATTEMPTS`). Below the cap the
   sweep is still retrying and will likely succeed, so reporting it would be noise about
   a problem that is fixing itself.
3. Reminders due inside the next 24h, plus any already-overdue pending row — an overdue
   reminder means the per-minute sweep is failing to deliver, which is worth saying.
4. The operator's own ops draft left `awaiting_confirm` — a conversation the CEO started
   and never finished.
5. Lớp B actions sitting `pending` in any agent's approval queue — work an agent has
   already stopped doing while it waits for a human, across the whole fleet.

Plus one signal that is NOT a query: the scratch checklist. The CEO can say "để ý giùm X"
about something the system has no column for, so it does not guess a status — it simply
echoes their own words back every `SCRATCH_REMIND_HOURS`, and stays quiet in between.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

#: How far ahead reminders count as "coming up".
REMINDER_HORIZON_HOURS = 24

#: An `awaiting_confirm` draft younger than this is just a conversation in progress, not
#: something to nag about. Matches `ops_conversation_store.DRAFT_TTL_S` (30m): past the
#: TTL the draft is dead anyway and the CEO's request is silently lost unless we say so.
STALE_DRAFT_MINUTES = 30


@dataclass(frozen=True)
class HeartbeatDigest:
    """What needs attention right now. Falsy when there is nothing (the common case)."""

    stalled: tuple[dict, ...] = ()
    undelivered: tuple[dict, ...] = ()
    reminders: tuple[dict, ...] = ()
    stale_drafts: tuple[dict, ...] = ()
    #: Lớp B actions waiting on a human, across every enabled agent. Every pending row is
    #: reported regardless of age: unlike a draft (which the CEO abandoned by choice), a
    #: pending approval is an agent BLOCKED — there is no threshold at which it stops
    #: mattering, and the queue is normally empty so this costs nothing when quiet.
    approvals: tuple[dict, ...] = ()
    #: Things the CEO asked to be kept an eye on. Unlike the four signals above these are
    #: NOT derived from any column — the system has no data about them, so it only echoes
    #: the CEO's own words back on a slow cadence rather than inventing a status.
    scratch: tuple[dict, ...] = ()
    #: Signals that could not be read this pulse (store missing/corrupt). Kept so a
    #: degraded read is visible rather than silently indistinguishable from "all clear".
    errors: tuple[str, ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:
        """True when there is something worth telling the CEO. Read errors alone do NOT
        make a digest truthy — a transient unreadable store must not wake the CEO."""
        return bool(self.stalled or self.undelivered or self.reminders
                    or self.stale_drafts or self.approvals or self.scratch)

    def item_keys(self) -> tuple[str, ...]:
        """One stable id PER PROBLEM — the unit the 'already told them' dedup works on.

        Deliberately per-item, not one key for the whole snapshot. A single set-shaped key
        fails two ways that matter in production: (a) any churn in the set (the rolling
        24h reminder horizon crosses one reminder at a time, and a re-stalled task flips
        back and forth) makes every pulse look "new", which is how a 30-minute heartbeat
        turns into 48 DMs a day; and (b) a problem that resolves and RECURS reproduces the
        old key, so it is silently swallowed forever. Tracking each problem on its own
        makes "tell the CEO once per problem" mean exactly that.

        An approval keys on `<agent>:<id>` alone. A row that an approve attempt reverts to
        `pending` (the handler failed after the CAS) therefore reproduces its old key and
        stays muted. That is a deliberate trade-off, not an oversight: the CEO already got
        the failure told to them directly in chat at the moment they approved it, so a
        second nudge from the heartbeat would repeat what they just read. Adding an
        attempt counter to the key would only matter if approvals could fail somewhere the
        CEO is not watching.
        """
        return tuple(sorted(
            [
                *(f"stalled:{t['id']}" for t in self.stalled),
                *(f"undelivered:{t['id']}" for t in self.undelivered),
                *(f"reminder:{r['id']}" for r in self.reminders),
                *(f"draft:{d['key']}:{d['command_id']}" for d in self.stale_drafts),
                *(f"approval:{a['agent_id']}:{a['id']}" for a in self.approvals),
                # Keyed on the ECHO, not the item: a scratch item is meant to come back
                # every SCRATCH_REMIND_HOURS, so each new echo has to read as new. Keying
                # on the id alone would announce it once and then mute it forever.
                *(f"scratch:{s['id']}:{s['echo']}" for s in self.scratch),
            ]
        ))


def build_digest(agent_id: str, *, now: datetime | None = None) -> HeartbeatDigest:
    """Collect the five signals. Each is best-effort: one unreadable store degrades that
    signal to an error string instead of losing the whole pulse."""
    now = now or datetime.now(UTC)
    errors: list[str] = []
    stalled = _collect(errors, "stalled", _stalled_tasks)
    undelivered = _collect(errors, "undelivered", _undelivered_tasks)
    reminders = _collect(errors, "reminders", lambda: _due_reminders(agent_id, now))
    drafts = _collect(errors, "drafts", lambda: _stale_drafts(agent_id, now))
    approvals = _collect(errors, "approvals", _pending_approvals)
    scratch = _collect(errors, "scratch", lambda: _due_scratch(agent_id, now))
    return HeartbeatDigest(
        stalled=stalled, undelivered=undelivered, reminders=reminders,
        stale_drafts=drafts, approvals=approvals, scratch=scratch, errors=tuple(errors),
    )


def _pending_approvals() -> list[dict]:
    """Every agent's pending Lớp B queue, read read-only.

    Uses `read_pending_actions`, which RAISES on an unreadable approvals db, rather than
    the fleet-view reader that degrades to `[]`. The difference is load-bearing here: the
    runner prunes its reported set to the keys the digest currently reports, so a swallowed
    error would read as "nothing is pending anymore", drop every key, and re-announce the
    whole queue on the next pulse. Letting it raise turns it into an `errors` entry, which
    is precisely what makes the runner keep the old set instead.

    One unreadable agent therefore costs the WHOLE approvals signal for that pulse. That is
    the safe direction: reporting a partial queue as if it were complete is what causes the
    storm, and the next clean pulse recovers.
    """
    from my_crew.actions.approval_summary import summarize_action
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.agent_state_reader import read_pending_actions
    from my_crew.runtime.registry import load_registry

    out: list[dict] = []
    for entry in load_registry():
        if not getattr(entry, "enabled", True):
            continue
        for row in read_pending_actions(agent_data_dir(entry.id)):
            out.append({
                "id": row["id"],
                "agent_id": entry.id,
                "summary": summarize_action(row.get("action") or {}),
            })
    return out


def _due_scratch(agent_id: str, now: datetime) -> list[dict]:
    """Scratch items due for their periodic echo. Read-only — the items are marked as
    echoed by the RUNNER, and only once a pulse actually reports, so a deferred or
    undelivered pulse does not silently consume the CEO's reminder."""
    store = open_state(agent_id)
    try:
        # `echo` buckets the item by which reminder window it belongs to, so a re-echo
        # 24h later is a different key from the first one (see `item_keys`).
        return [
            {"id": item["id"], "text": item["text"],
             "echo": (item["last_echoed_at"] or "first")}
            for item in store.due_scratch(now=now)
        ]
    finally:
        store.close()


def _collect(errors: list[str], name: str, fn) -> tuple[dict, ...]:
    try:
        return tuple(fn())
    except Exception as exc:  # noqa: BLE001 — a broken store degrades one signal, not the pulse
        logger.warning("heartbeat digest: %s unreadable: %s", name, exc)
        errors.append(name)
        return ()


def _stalled_tasks() -> list[dict]:
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    try:
        return [{"id": t.id, "title": t.title} for t in store.list_stalled()]
    finally:
        store.close()


def _undelivered_tasks() -> list[dict]:
    """Only tasks the delivery-retry sweep has GIVEN UP on. Below the cap the sweep owns
    the row and is still retrying (see `delivery_retry_sweep`), so surfacing it would ping
    the CEO about something being handled automatically."""
    from my_crew.runtime.delivery_retry_sweep import MAX_DELIVERY_ATTEMPTS
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    try:
        return [
            {"id": t.id, "title": t.title, "attempts": t.delivery_attempts}
            for t in store.list_undelivered()
            if t.delivery_attempts >= MAX_DELIVERY_ATTEMPTS
        ]
    finally:
        store.close()


def _due_reminders(agent_id: str, now: datetime) -> list[dict]:
    """Pending reminders firing within the horizon, including already-overdue rows.

    `due_at` is RFC3339 WITH an offset, so it is parsed and compared as a datetime —
    string comparison is wrong here (`+07:00` and `Z` do not sort lexicographically).
    """
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.reminder_store import ReminderStore, reminders_db_path

    horizon = now + timedelta(hours=REMINDER_HORIZON_HOURS)
    store = ReminderStore(reminders_db_path(agent_data_dir(agent_id)))
    try:
        out = []
        for row in store.list_pending():
            try:
                due = datetime.fromisoformat(row["due_at"])
            except ValueError:
                continue  # unparsable rows can't reach here via the gateway; skip defensively
            if due.tzinfo is None:
                due = due.replace(tzinfo=UTC)
            if due <= horizon:
                out.append({"id": row["id"], "text": row["text"], "due_at": row["due_at"],
                            "overdue": due <= now})
        return out
    finally:
        store.close()


def _stale_drafts(agent_id: str, now: datetime) -> list[dict]:
    """The operator's own half-finished ops commands, read WITHOUT mutating.

    `OpsConversationStore.load()` deletes TTL-expired drafts as a side effect, so a
    read-only digest must not use it — a stale draft has to survive being reported.
    """
    import sqlite3

    from my_crew.runtime.agent_paths import agent_data_dir

    db = agent_data_dir(agent_id) / "ops_conversation.sqlite3"
    if not db.exists():
        return []
    cutoff = now.timestamp() - STALE_DRAFT_MINUTES * 60
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT conversation_key, command_id, updated_at FROM ops_drafts "
            "WHERE phase = 'awaiting_confirm' AND updated_at <= ? ORDER BY updated_at",
            (cutoff,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []  # table not created yet on a fresh agent
    finally:
        conn.close()
    return [{"key": k, "command_id": c, "updated_at": u} for k, c, u in rows]


def format_digest(digest: HeartbeatDigest) -> str:
    """Render the digest as the CEO-facing Telegram text. Kept short on purpose — this is
    a nudge, not a report; the CEO opens the cockpit for detail."""
    lines: list[str] = []
    if digest.stalled:
        lines.append(f"⏸ {len(digest.stalled)} việc đang kẹt:")
        lines += [f"  • {t['title']}" for t in digest.stalled[:5]]
    if digest.undelivered:
        lines.append(f"📭 {len(digest.undelivered)} kết quả không gửi được:")
        lines += [f"  • {t['title']}" for t in digest.undelivered[:5]]
    if digest.reminders:
        overdue = [r for r in digest.reminders if r["overdue"]]
        upcoming = [r for r in digest.reminders if not r["overdue"]]
        if overdue:
            lines.append(f"🔴 {len(overdue)} nhắc hẹn quá hạn chưa gửi được:")
            lines += [f"  • {r['text']}" for r in overdue[:5]]
        if upcoming:
            lines.append(f"⏰ {len(upcoming)} nhắc hẹn trong 24h tới:")
            lines += [f"  • {r['text']}" for r in upcoming[:5]]
    if digest.stale_drafts:
        lines.append(f"✍️ {len(digest.stale_drafts)} lệnh còn dở chờ CEO xác nhận:")
        lines += [f"  • {d['command_id']}" for d in digest.stale_drafts[:5]]
    if digest.approvals:
        lines.append(f"🔐 {len(digest.approvals)} việc chờ CEO duyệt:")
        lines += [f"  • #{a['id']} · {a['agent_id']} · {a['summary']}"
                  for a in digest.approvals[:5]]
    if digest.scratch:
        # Phrased as a reminder, never as a status. The system has no signal for these —
        # claiming "X vẫn ổn" would be an invented fact.
        lines.append(f"📌 {len(digest.scratch)} việc CEO dặn để ý:")
        lines += [f"  • {s['text']}" for s in digest.scratch[:5]]
    return "\n".join(lines)


def open_state(agent_id: str):
    """The agent's heartbeat state store. Callers MUST close it."""
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.heartbeat_state_store import HeartbeatStateStore, heartbeat_db_path

    return HeartbeatStateStore(heartbeat_db_path(agent_data_dir(agent_id)))


def load_reported(agent_id: str) -> set[str]:
    """Problem keys the CEO has already been told about. An unreadable store means "told
    them nothing", which errs toward speaking up rather than silently swallowing."""
    try:
        store = open_state(agent_id)
    except Exception:  # noqa: BLE001 — a broken store must not kill the pulse
        logger.warning("heartbeat: state unreadable for %s", agent_id)
        return set()
    try:
        return store.load_reported()
    finally:
        store.close()


def unreported(digest: HeartbeatDigest, reported: set[str]) -> tuple[str, ...]:
    """The problems in this digest the CEO has NOT been told about yet."""
    return tuple(k for k in digest.item_keys() if k not in reported)


def save_reported(agent_id: str, keys: set[str]) -> None:
    """Persist the reported set, PRUNED to what is still live.

    Callers pass only keys present in the current digest, so a problem that resolves drops
    out — and if it ever comes back it counts as new and speaks up again. That pruning is
    the whole point: a resolved-then-recurring problem must not stay muted by a stale
    entry, and the set cannot grow without bound.
    """
    try:
        store = open_state(agent_id)
    except Exception:  # noqa: BLE001 — losing the dedup costs a duplicate, not the pulse
        logger.warning("heartbeat: could not persist state for %s", agent_id)
        return
    try:
        store.save_reported(keys)
    finally:
        store.close()
