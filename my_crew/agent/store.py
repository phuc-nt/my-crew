"""LangGraph Store factory for cross-thread agent memory (v2 M2-P8).

The Store is the durable, queryable backing for an agent's memory (facts the agent
remembers across report runs, namespaced by `agent_id`). It is INTERNAL agent state —
like the checkpointer — NOT an external mutation, so it does not go through the Action
Gateway.

`InMemoryStore` is the DEFAULT (no infra dependency; the memory does not survive a
process restart, which is fine for the SQLite-local default). `PostgresStore` is the
opt-in durable backend, selected by `settings.store == "postgres"` + a `postgres_dsn`.

Mirrors `checkpoint.py`: the Postgres branch opens the RAW connection directly (the
same kwargs `from_conn_string` uses) so the store owns a process-lifetime connection —
NOT `from_conn_string(...).__enter__()`, which would let GC close the connection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.store.memory import InMemoryStore

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore

    from my_crew.config.settings import Settings


def get_store(settings: Settings) -> BaseStore:
    """Return the Store the settings select.

    v66 (CEO 2026-08-04, SQLite-first cross-agent memory): "sqlite" is the NEW DEFAULT
    — one shared cross-agent file, so remembered facts survive the per-run worker
    process AND sibling reads see every group member's facts. Explicit "memory" keeps
    the old in-process store (byte-identical); "postgres" stays the opt-in durable
    backend for when a real concurrent-writer need is measured.
    """
    if settings.store == "postgres":
        return _postgres_store(settings)
    if settings.store == "sqlite":
        return _sqlite_store()
    # "memory" — and any unknown value — stays the in-process store (pre-v66 pin: an
    # unrecognized backend name must degrade safely, never invent persistence).
    return InMemoryStore()


def _sqlite_store() -> BaseStore:
    """Shared cross-agent SqliteStore at repo-root `.data/memory_store.sqlite3`.

    ONE file for the whole fleet (the point is cross-agent reads), WAL + busy_timeout
    for the multi-process reality every worker run lives in — the exact posture
    `team_task_store` has proven for months. Namespacing `(agent_id, "memory")` keeps
    per-agent isolation inside the shared file."""
    import sqlite3

    from langgraph.store.sqlite import SqliteStore

    from my_crew.runtime.team_task_paths import team_tasks_root

    path = team_tasks_root() / "memory_store.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None (autocommit): SqliteStore issues its own explicit BEGIN —
    # python-sqlite3's implicit transactions would nest and raise ("cannot start a
    # transaction within a transaction"), same connection posture its own
    # `from_conn_string` uses.
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=3000")
    store = SqliteStore(conn)
    store.setup()
    return store


def _postgres_store(settings: Settings) -> BaseStore:
    """Build a long-lived PostgresStore from the dsn (M2-P8, opt-in).

    Selection-tested only this round (no live Postgres); the real-PG runtime is
    verified later. Opens the raw connection directly (see the module docstring on the
    `from_conn_string().__enter__()` GC hazard).
    """
    if not settings.postgres_dsn:
        raise ValueError("store=postgres requires settings.postgres_dsn")
    from langgraph.store.postgres import PostgresStore
    from psycopg import Connection
    from psycopg.rows import dict_row

    conn = Connection.connect(
        settings.postgres_dsn, autocommit=True, prepare_threshold=0, row_factory=dict_row
    )
    store = PostgresStore(conn)
    store.setup()
    return store
