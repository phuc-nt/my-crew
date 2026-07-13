"""Checkpointer for the LangGraph agent (system-architecture.md §3, §5).

Provides resume + time-travel debug + an audit-friendly state trail. SQLite is the
DEFAULT (local-first, a single per-agent file, no infra dependency). Postgres is an
opt-in scale-up (M2-P8) for durable state across processes/machines, selected by
`settings.checkpointer == "postgres"` + a `postgres_dsn`.

Both savers are returned OPEN: `from_conn_string` is a context manager, so for a
long-lived CLI/worker/server process we open the underlying connection directly and
let the saver live for the process lifetime.
"""

from __future__ import annotations

import os
import sqlite3
from typing import TYPE_CHECKING

from langgraph.checkpoint.sqlite import SqliteSaver

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from src.config.settings import Settings

# Restrict checkpoint deserialization to plain data (no arbitrary code exec) if a
# checkpoint DB is ever tampered with. Set before the saver is used.
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")


def get_checkpointer(settings: Settings) -> BaseCheckpointSaver:
    """Open (and set up) the checkpointer the settings select.

    Default (`checkpointer="sqlite"`): a per-agent SQLite file at
    `settings.data_dir / "checkpoints.db"` (byte-identical to the pre-P8 path).
    `checkpointer="postgres"`: a `PostgresSaver` built from `settings.postgres_dsn`
    (raises if the dsn is missing). The Postgres path keeps the connection open for
    the process lifetime, the same way the SQLite path does.
    """
    if settings.checkpointer == "postgres":
        return _postgres_checkpointer(settings)
    db_path = settings.data_dir / "checkpoints.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def _postgres_checkpointer(settings: Settings) -> BaseCheckpointSaver:
    """Build a long-lived PostgresSaver from the dsn (M2-P8, opt-in).

    Mirrors the sqlite branch: open the RAW connection directly (the same kwargs
    `from_conn_string` uses internally) and hand it to the saver, so the saver owns a
    process-lifetime connection. We must NOT use `from_conn_string(...).__enter__()` —
    that leaves the context-manager generator unreferenced, so on GC its `__exit__`
    closes the connection out from under the saver.

    NOTE: this branch is selection-tested only this round (no live Postgres); the
    real-PG runtime (incl. whether a connection pool is wanted for concurrency) is
    verified in a later round.
    """
    if not settings.postgres_dsn:
        raise ValueError("checkpointer=postgres requires settings.postgres_dsn")
    # Lazy imports: the postgres extra is optional; only loaded on the opt-in path.
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg import Connection
    from psycopg.rows import dict_row

    conn = Connection.connect(
        settings.postgres_dsn, autocommit=True, prepare_threshold=0, row_factory=dict_row
    )
    saver = PostgresSaver(conn)
    saver.setup()
    return saver


def get_team_checkpointer() -> BaseCheckpointSaver:
    """Checkpointer for TEAM-TASK step graphs (v34 P1) — a SEPARATE SQLite file at
    the shared cross-agent root, NOT any agent's per-agent `checkpoints.db`.

    Separate because: (a) a team step is cross-agent by design (same reasoning as the
    team-task store living at the shared root), and (b) the ticker and several worker
    processes all touch it — sharing a file with the report-graph checkpointer would
    couple their lock behavior for zero gain. WAL + busy_timeout for the same
    multi-process reality the team-task store handles.

    Threads are cleaned up eagerly (delete on step completion) plus swept by the
    ticker for tasks that ended without a clean delete — see
    `team_step_runner`/`team_tick_runner`.
    """
    from src.runtime.team_task_paths import team_checkpoints_db_path

    db_path = team_checkpoints_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    saver = SqliteSaver(conn)
    saver.setup()
    return saver
