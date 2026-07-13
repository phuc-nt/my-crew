"""Shared `schema_meta` versioning for the team-side SQLite stores (v36 P1 G2).

The stores grew migrate-free (`CREATE IF NOT EXISTS` + additive `ALTER ADD COLUMN`),
which has no audit trail and no way to branch on a past schema. This adds a tiny
`schema_meta(key, value)` table carrying a `schema_version` int so a future migration
can detect and act on an old shape. It does NOT change any data — a store opened without
the table simply adopts the current version.

Applied only to the stores THIS project owns and migrates (team_tasks, captures,
office_room, clarify). langgraph-owned checkpoint DBs and per-agent approvals/dedup are
out of scope — their schemas are not ours to version.
"""

from __future__ import annotations

import sqlite3

#: Current schema version. Bump when a real migration lands (and add the migration that
#: reads this value). v36 establishes the baseline at 1 for every store below.
SCHEMA_VERSION = 1


def ensure_schema_meta(conn: sqlite3.Connection, *, version: int = SCHEMA_VERSION) -> int:
    """Create `schema_meta` if absent and record `version` when unset. Returns the stored
    version. Idempotent: an already-stamped store keeps its recorded version (adopt path
    for a DB created before this table existed — it takes `version` on first open)."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta ("
        "  key TEXT PRIMARY KEY,"
        "  value TEXT NOT NULL"
        ")"
    )
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?)",
            (str(version),),
        )
        conn.commit()
        return version
    return int(row[0])


def read_schema_version(conn: sqlite3.Connection) -> int | None:
    """The recorded schema version, or None if the store predates schema_meta."""
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return int(row[0]) if row else None
