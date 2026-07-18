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
    """Return the Store the settings select (InMemoryStore default / PostgresStore opt-in)."""
    if settings.store == "postgres":
        return _postgres_store(settings)
    return InMemoryStore()


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
