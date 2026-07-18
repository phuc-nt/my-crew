"""M2-P8 Slice 2: Store selection (InMemoryStore default / PostgresStore opt-in).

Offline: the memory branch builds a real InMemoryStore; the postgres branch is
SELECTION-tested by patching the raw connect + PostgresStore ctor (NO live PG). Plus an
integration check that a compiled graph's node sees the store via its `store=` param.
"""

from __future__ import annotations

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from typing_extensions import TypedDict

from my_crew.agent.store import get_store
from my_crew.config.config_builders import build_settings_from_dict


def test_default_is_in_memory_store():
    store = get_store(build_settings_from_dict({}))
    assert isinstance(store, InMemoryStore)


def test_postgres_store_branch_reached_with_dsn(monkeypatch):
    seen = {}

    def _fake_connect(dsn, **kwargs):
        seen["dsn"] = dsn
        seen["kwargs"] = kwargs
        return object()

    class _FakeStore:
        def __init__(self, conn):
            seen["conn"] = conn

        def setup(self):
            seen["setup"] = True

    import langgraph.store.postgres as pg
    import psycopg

    monkeypatch.setattr(psycopg.Connection, "connect", staticmethod(_fake_connect))
    monkeypatch.setattr(pg, "PostgresStore", _FakeStore)
    settings = build_settings_from_dict({"store": "postgres", "postgres_dsn": "postgresql://x/y"})
    store = get_store(settings)
    assert seen["dsn"] == "postgresql://x/y"
    # kwargs must match what from_conn_string uses internally (so the store behaves
    # identically minus the GC-closing context-manager generator).
    from psycopg.rows import dict_row

    assert seen["kwargs"]["autocommit"] is True
    assert seen["kwargs"]["prepare_threshold"] == 0
    assert seen["kwargs"]["row_factory"] is dict_row
    assert seen["setup"] is True
    assert isinstance(store, _FakeStore)


def test_postgres_store_without_dsn_raises():
    settings = build_settings_from_dict({"store": "postgres"})
    with pytest.raises(ValueError, match="postgres_dsn"):
        get_store(settings)


def test_unknown_store_falls_back_to_memory():
    assert isinstance(get_store(build_settings_from_dict({"store": "bogus"})), InMemoryStore)


# --- a compiled graph's node sees the store via its store= param ---


class _S(TypedDict, total=False):
    seen_store: bool


def test_compiled_graph_node_receives_store():
    seen = {}

    def _node(state, *, store: BaseStore = None):
        seen["store"] = store
        return {"seen_store": store is not None}

    builder = StateGraph(_S)
    builder.add_node("n", _node)
    builder.add_edge(START, "n")
    builder.add_edge("n", END)
    graph = builder.compile(store=InMemoryStore())
    out = graph.invoke({})
    assert out["seen_store"] is True
    assert isinstance(seen["store"], InMemoryStore)
