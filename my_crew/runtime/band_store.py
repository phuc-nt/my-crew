"""Autonomy bands per agent (v76 phase 3, learned from my-dandori `govern/bands.go`).

`supervised | normal | trusted` — the ONLY thing a band may change is the peer-review
gate (see `review_insert.effective_needs_review`): supervised forces a review row on
every work step; trusted widens the small-task waiver to ordinary steps (terminal and
external-write steps are ALWAYS reviewed regardless). The plan invariant is a test,
not a comment: bands never touch dispatch/concurrency/poke, consults, fan-out, Lớp A,
the gateway, budgets, or the autopilot ladder — an agent's autonomy of MOVEMENT is
untouched; only how much of its output gets a second pair of eyes.

Fail direction (my-dandori's asymmetry, kept): no row → "normal" (default posture);
a BROKEN store → "supervised" (strict) — a failure while answering a trust question
must never answer "trust more".
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

BAND_SUPERVISED = "supervised"
BAND_NORMAL = "normal"
BAND_TRUSTED = "trusted"
_BANDS = (BAND_SUPERVISED, BAND_NORMAL, BAND_TRUSTED)


def _db_path() -> Path:
    from my_crew.config.settings import DATA_DIR

    return DATA_DIR / "agent_bands.sqlite3"


class BandStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self._conn = sqlite3.connect(db_path or _db_path())
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_bands ("
            "  agent_id TEXT PRIMARY KEY,"
            "  band TEXT NOT NULL,"
            "  reason TEXT NOT NULL DEFAULT '',"
            "  changed_by TEXT NOT NULL DEFAULT '',"
            "  updated_at TEXT NOT NULL"
            ")"
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def get(self, agent_id: str) -> str:
        row = self._conn.execute(
            "SELECT band FROM agent_bands WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        band = str(row[0]) if row else BAND_NORMAL
        return band if band in _BANDS else BAND_NORMAL

    def set(self, agent_id: str, band: str, *, reason: str, changed_by: str) -> None:
        if band not in _BANDS:
            raise ValueError(f"band không hợp lệ: {band!r} (chọn: {', '.join(_BANDS)})")
        self._conn.execute(
            "INSERT INTO agent_bands (agent_id, band, reason, changed_by, updated_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(agent_id) DO UPDATE SET "
            "band=excluded.band, reason=excluded.reason, changed_by=excluded.changed_by, "
            "updated_at=excluded.updated_at",
            (agent_id, band, reason, changed_by, datetime.now(UTC).isoformat()),
        )
        self._conn.commit()

    def updated_at(self, agent_id: str) -> str:
        row = self._conn.execute(
            "SELECT updated_at FROM agent_bands WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        return str(row[0]) if row else ""


def band_for(agent_id: str) -> str:
    """The one read every consumer uses. Never raises.

    No store FILE at all → normal without creating one (a fleet that never used bands
    keeps zero side effects, and test isolation holds). File present but BROKEN →
    supervised (fail-strict: a failure while answering a trust question must never
    answer "trust more"). Missing row → normal.
    """
    try:
        if not _db_path().exists():
            return BAND_NORMAL
        store = BandStore()
        try:
            return store.get(agent_id)
        finally:
            store.close()
    except Exception:  # noqa: BLE001 — fail-strict, see docstring
        logger.warning("band_for(%s): store unavailable — falling back to supervised",
                       agent_id, exc_info=True)
        return BAND_SUPERVISED
