"""M2-P8 Slice 1: checkpointer selection (sqlite default / postgres opt-in).

Offline: the sqlite branch uses a real SqliteSaver at a tmp data_dir; the postgres
branch is SELECTION-tested by patching the PostgresSaver constructor (NO live PG).
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from my_crew.agent.checkpoint import get_checkpointer
from my_crew.config.config_builders import build_settings_from_dict


def test_default_is_sqlite_at_data_dir(tmp_path):
    settings = build_settings_from_dict({"data_dir": tmp_path})
    cp = get_checkpointer(settings)
    assert isinstance(cp, SqliteSaver)
    assert (tmp_path / "checkpoints.db").exists()  # byte-identical pre-P8 path


def test_postgres_branch_reached_with_dsn(tmp_path, monkeypatch):
    # Patch the raw psycopg connect + the PostgresSaver ctor so NO real connection is
    # made; assert the postgres branch is reached with the dsn (and opens the raw
    # connection directly, not via from_conn_string — see C1 fix).
    seen = {}

    def _fake_connect(dsn, **kwargs):
        seen["dsn"] = dsn
        seen["kwargs"] = kwargs
        return object()  # a stand-in connection; never used (saver is faked too)

    class _FakeSaver:
        def __init__(self, conn):
            seen["conn_passed"] = conn

        def setup(self):
            seen["setup"] = True

    import langgraph.checkpoint.postgres as pg
    import psycopg

    monkeypatch.setattr(psycopg.Connection, "connect", staticmethod(_fake_connect))
    monkeypatch.setattr(pg, "PostgresSaver", _FakeSaver)
    settings = build_settings_from_dict(
        {"data_dir": tmp_path, "checkpointer": "postgres", "postgres_dsn": "postgresql://x/y"}
    )
    cp = get_checkpointer(settings)
    from psycopg.rows import dict_row

    assert seen["dsn"] == "postgresql://x/y"
    # kwargs mirror from_conn_string (identical saver behavior minus the GC-close CM).
    assert seen["kwargs"]["autocommit"] is True
    assert seen["kwargs"]["prepare_threshold"] == 0
    assert seen["kwargs"]["row_factory"] is dict_row
    assert seen["setup"] is True
    assert isinstance(cp, _FakeSaver)


def test_postgres_without_dsn_raises(tmp_path):
    settings = build_settings_from_dict({"data_dir": tmp_path, "checkpointer": "postgres"})
    with pytest.raises(ValueError, match="postgres_dsn"):
        get_checkpointer(settings)


def test_unknown_checkpointer_falls_back_to_sqlite(tmp_path):
    # Anything not "postgres" → the sqlite path (defensive default).
    settings = build_settings_from_dict({"data_dir": tmp_path, "checkpointer": "bogus"})
    assert isinstance(get_checkpointer(settings), SqliteSaver)


# --- 3-tier config resolution (yaml → env → default) ---


def test_config_default_sqlite_memory():
    s = build_settings_from_dict({})
    assert s.checkpointer == "sqlite"
    assert s.store == "memory"
    assert s.postgres_dsn is None


def test_config_explicit_postgres():
    s = build_settings_from_dict(
        {"checkpointer": "postgres", "store": "postgres", "postgres_dsn": "postgresql://h/d"}
    )
    assert s.checkpointer == "postgres" and s.store == "postgres"
    assert s.postgres_dsn == "postgresql://h/d"


def test_profile_yaml_runtime_block_maps(tmp_path, monkeypatch):
    # A profile.yaml runtime: block resolves through build_settings_dict (yaml wins).
    from my_crew.profile.loader_mapping import build_settings_dict

    monkeypatch.delenv("CHECKPOINTER_TYPE", raising=False)
    monkeypatch.delenv("STORE_TYPE", raising=False)
    yaml_doc = {"runtime": {"checkpointer": "postgres", "store": "postgres",
                            "postgres_dsn": "postgresql://h/d"}}
    d = build_settings_dict(yaml_doc, tmp_path)
    s = build_settings_from_dict(d)
    assert s.checkpointer == "postgres" and s.store == "postgres"
    assert s.postgres_dsn == "postgresql://h/d"


def test_profile_yaml_empty_runtime_defers_to_default(tmp_path, monkeypatch):
    from my_crew.profile.loader_mapping import build_settings_dict

    monkeypatch.delenv("CHECKPOINTER_TYPE", raising=False)
    monkeypatch.delenv("STORE_TYPE", raising=False)
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    yaml_doc = {"runtime": {"checkpointer": "", "store": "", "postgres_dsn": ""}}
    d = build_settings_dict(yaml_doc, tmp_path)
    s = build_settings_from_dict(d)
    assert s.checkpointer == "sqlite" and s.store == "memory" and s.postgres_dsn is None
