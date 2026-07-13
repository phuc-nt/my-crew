"""Storage hygiene: retention GC + integrity audit for the team-side stores (v36 P1).

Three append-only stores (captures/office_room/clarify) and the per-agent dedup store
had NO garbage collection — only amendment-drafts, history-index, and checkpoints were
swept. Left alone they grow without bound (telemetry per attempt, office feed per event).
This module adds an age-based sweep and a read-only integrity audit, both best-effort so
a failure never blocks the scheduler tick that calls them (mirrors the sandbox reaper).

Retention (CEO 2026-07-13, "giữ lâu hơn" — audit-friendly, still bounded):
- captures       180d   (per-attempt telemetry)
- office_room     90d   (Văn phòng event feed)
- clarify         90d   (answered/expired only; pending never removed)
- dedup (agent)    7d   (idempotency window, not audit data — kept short)

team_tasks / team_steps are NOT swept here — they are business history, kept for now.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

#: Days of history each store keeps. Module constants (not runtime config) — change by
#: editing here; a single-user product does not need a settings surface for this (YAGNI).
RETENTION_DAYS = {
    "captures": 180,
    "office_room": 90,
    "clarify": 90,
    "dedup": 7,
}

#: The integrity audit is read-only but not free — run it at most once per local day,
#: stamped in a sidecar next to the shared stores.
_AUDIT_STATE_FILE = "storage_audit_state.json"


def _cutoff_iso(days: int, now: datetime) -> str:
    return (now - timedelta(days=days)).isoformat()


def run_retention_sweep(*, now: datetime | None = None) -> dict[str, int]:
    """Delete over-age rows from the shared + per-agent stores. Returns {store: n_deleted}.

    Each store is swept independently and defensively: a failure on one is logged and the
    sweep continues, so one locked/corrupt DB never blocks retention on the others.
    """
    now = now or datetime.now(UTC)  # aware UTC — row timestamps are all UTC ISO
    deleted: dict[str, int] = {}

    def _sweep(label: str, opener, days: int) -> None:
        try:
            store = opener()
            try:
                deleted[label] = store.delete_older_than(_cutoff_iso(days, now))
            finally:
                store.close()
        except Exception:  # noqa: BLE001 — retention is best-effort per store
            logger.warning("retention sweep failed for %s (ignored)", label, exc_info=True)

    from src.runtime.capture_store import CaptureStore
    from src.runtime.clarify_store import ClarifyStore
    from src.runtime.office_room_store import OfficeRoomStore, office_room_db_path
    from src.runtime.team_task_paths import capture_db_path, clarify_db_path, team_tasks_root

    _sweep("captures", lambda: CaptureStore(capture_db_path()), RETENTION_DAYS["captures"])
    _sweep(
        "office_room",
        lambda: OfficeRoomStore(office_room_db_path(team_tasks_root())),
        RETENTION_DAYS["office_room"],
    )
    _sweep("clarify", lambda: ClarifyStore(clarify_db_path()), RETENTION_DAYS["clarify"])
    _sweep_dedup(deleted, now)
    return deleted


def _sweep_dedup(deleted: dict[str, int], now: datetime) -> None:
    """Purge each enabled agent's per-agent dedup store; one broken agent never blocks
    the rest. Aggregated under the 'dedup' key."""
    from src.actions.dedup_store import DedupStore
    from src.runtime.agent_paths import agent_data_dir
    from src.runtime.registry import load_registry

    cutoff = _cutoff_iso(RETENTION_DAYS["dedup"], now)
    total = 0
    for entry in load_registry():
        if not getattr(entry, "enabled", False):
            continue
        db = agent_data_dir(entry.id) / "dedup.db"
        if not db.exists():
            continue
        try:
            store = DedupStore(db)
            try:
                total += store.delete_older_than(cutoff)
            finally:
                store.close()
        except Exception:  # noqa: BLE001 — per-agent isolation
            logger.warning("dedup sweep failed for %s (ignored)", entry.id, exc_info=True)
    deleted["dedup"] = total


def run_integrity_audit(*, now: datetime | None = None) -> list[str]:
    """Read-only orphan scan; logs a WARNING with counts + examples, mutates nothing.

    Daily-gated via a sidecar stamp. Returns the warning lines emitted (empty when
    gated off or clean) so the caller/tests can assert on them.
    """
    now = now or datetime.now(UTC)  # aware UTC — row timestamps are all UTC ISO
    if not _audit_due(now):
        return []
    _stamp_audit(now)
    warnings: list[str] = []
    try:
        warnings = _scan_orphans()
    except Exception:  # noqa: BLE001 — audit is advisory, never fatal
        logger.warning("integrity audit failed (ignored)", exc_info=True)
        return []
    for line in warnings:
        logger.warning("integrity audit: %s", line)
    return warnings


def _scan_orphans() -> list[str]:
    """Two read-only checks: step rows without a parent task, and artifact dirs without a
    task row. Returns human-readable warning lines (count + up to 5 example ids)."""
    import sqlite3

    from src.runtime.team_task_paths import team_tasks_db_path, team_tasks_root

    lines: list[str] = []
    db = team_tasks_db_path()
    if db.exists():
        conn = sqlite3.connect(str(db))
        try:
            task_ids = {r[0] for r in conn.execute("SELECT id FROM team_tasks")}
            orphan_steps = [
                r[0]
                for r in conn.execute("SELECT task_id FROM team_steps")
                if r[0] not in task_ids
            ]
        finally:
            conn.close()
        if orphan_steps:
            uniq = sorted(set(orphan_steps))
            lines.append(
                f"{len(orphan_steps)} step rows reference {len(uniq)} missing task(s): "
                f"{uniq[:5]}"
            )
        # Artifact dirs (.data/team-tasks/<task>/) with no task row.
        art_root = team_tasks_root() / "team-tasks"
        if art_root.is_dir():
            orphan_dirs = [
                d.name for d in art_root.iterdir() if d.is_dir() and d.name not in task_ids
            ]
            if orphan_dirs:
                lines.append(
                    f"{len(orphan_dirs)} artifact dir(s) have no task row: {orphan_dirs[:5]}"
                )
    return lines


def _audit_state_path():
    from src.runtime.team_task_paths import team_tasks_root

    return team_tasks_root() / _AUDIT_STATE_FILE


def _audit_due(now: datetime) -> bool:
    import json

    path = _audit_state_path()
    try:
        last = datetime.fromisoformat(
            json.loads(path.read_text(encoding="utf-8")).get("last_audit", "")
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return True
    try:
        return (now - last) >= timedelta(days=1)
    except TypeError:
        return (now.replace(tzinfo=None) - last.replace(tzinfo=None)) >= timedelta(days=1)


def _stamp_audit(now: datetime) -> None:
    import json

    path = _audit_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_audit": now.isoformat()}), encoding="utf-8")
