"""SQLite checkpointer for the LangGraph agent (system-architecture.md §3, §5).

Provides resume + time-travel debug + an audit-friendly state trail. Local-first:
a single SQLite file under the data dir (Postgres is the scale-up path, not now).

The checkpointer is returned as an open SqliteSaver. `from_conn_string` is a
context manager; for a long-lived CLI/process we open it directly via the
underlying connection so the saver stays usable for the process lifetime.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from src.config.settings import get_settings

# Restrict checkpoint deserialization to plain data (no arbitrary code exec) if a
# checkpoint DB is ever tampered with. Set before the saver is used.
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")


def get_checkpointer(db_path: Path | None = None) -> SqliteSaver:
    """Open (and set up) a SQLite checkpointer at the given path.

    Creates the parent dir and the checkpoint tables if missing. The connection
    uses check_same_thread=False so a CLI invocation can use it across the call.
    """
    path = db_path or (get_settings().data_dir / "checkpoints.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver
