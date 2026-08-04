"""v66 cross-agent memory, SQLite-first: shared persistent store (new default), the
secretary's read-only privacy rule, injection-wrapped sibling block, and retention."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from my_crew.agent.store import get_store


@pytest.fixture(autouse=True)
def _isolated_shared_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    return tmp_path


# --- backend selection + persistence -------------------------------------------------


def test_absent_store_config_defaults_to_sqlite():
    from my_crew.config.config_builders import build_settings_from_dict

    assert build_settings_from_dict({}).store == "sqlite"
    assert build_settings_from_dict({"store": "memory"}).store == "memory"  # explicit kept


def test_sqlite_store_persists_across_instances(tmp_path):
    """The whole point: a fact written by one worker PROCESS must be readable by the
    next — two independent store instances over the same shared file stand in for two
    processes."""
    settings = SimpleNamespace(store="sqlite", postgres_dsn=None)
    store_a = get_store(settings)
    store_a.put(("researcher", "memory"), "fact-1", {"fact": "Postgres ~3.5tr/tháng",
                                                     "ts": datetime.now(UTC).isoformat()})
    store_b = get_store(settings)  # fresh connection, same file
    items = list(store_b.search(("researcher", "memory"), limit=10))
    assert [i.value["fact"] for i in items] == ["Postgres ~3.5tr/tháng"]
    assert (tmp_path / "memory_store.sqlite3").exists()


def test_memory_store_keeps_in_process_behavior():
    settings = SimpleNamespace(store="memory", postgres_dsn=None)
    store_a = get_store(settings)
    store_a.put(("x", "memory"), "k", {"fact": "f", "ts": "t"})
    store_b = get_store(settings)  # a NEW InMemoryStore — nothing shared
    assert list(store_b.search(("x", "memory"), limit=10)) == []


# --- memory_share privacy rule -------------------------------------------------------


def _entry(agent_id):
    return SimpleNamespace(id=agent_id, enabled=True)


def _mk_profile(agent_id, group="company", share="full"):
    return SimpleNamespace(profile_id=agent_id, project_group=group, memory_share=share)


def test_read_only_sibling_is_never_a_fact_source(monkeypatch):
    from my_crew.agent import sibling_memory

    profiles = {
        "researcher": _mk_profile("researcher"),
        "secretary": _mk_profile("secretary", share="read_only"),
        "analyst": _mk_profile("analyst"),
    }
    monkeypatch.setattr(sibling_memory, "load_profile",
                        lambda agent_id, **kw: profiles[agent_id])
    registry = tuple(_entry(a) for a in ("researcher", "secretary", "analyst"))

    # Another group member building context: secretary is EXCLUDED as a source…
    assert sibling_memory.enumerate_siblings("analyst", "company", registry) == ["researcher"]
    # …while the secretary itself still reads every full-share sibling.
    assert sibling_memory.enumerate_siblings("secretary", "company", registry) == [
        "researcher", "analyst",
    ]


def test_loader_rejects_unknown_memory_share_value(tmp_path):
    from my_crew.profile.loader import load_profile

    profile_dir = tmp_path / "profiles" / "agent-x"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.yaml").write_text(
        "name: X\nmemory_share: everyone\n", encoding="utf-8",
    )
    with pytest.raises((RuntimeError, FileNotFoundError), match="memory_share|env"):
        load_profile("agent-x", profiles_dir=tmp_path / "profiles",
                     data_dir=tmp_path / "data")


# --- injection wrap ------------------------------------------------------------------


def test_sibling_block_is_wrapped_not_raw():
    from my_crew.agent.sibling_selector import render_sibling_facts

    block = render_sibling_facts(["deadline dời sang thứ 6"], "company")
    assert "deadline dời sang thứ 6" in block
    # The formatter's structural delimiters must be present — raw label-join was the
    # pre-v66 shape, unacceptable now that facts persist across days.
    assert block != ("--- Bộ nhớ agent khác (project: company) ---\n"
                     "deadline dời sang thứ 6")
    assert render_sibling_facts([], "company") == ""


# --- retention -----------------------------------------------------------------------


def test_retention_prunes_only_over_age_facts(monkeypatch, tmp_path):
    from my_crew.runtime.storage_hygiene import run_retention_sweep

    monkeypatch.setattr("my_crew.runtime.registry.load_registry",
                        lambda: (_entry("researcher"),))
    settings = SimpleNamespace(store="sqlite", postgres_dsn=None)
    store = get_store(settings)
    now = datetime.now(UTC)
    store.put(("researcher", "memory"), "old",
              {"fact": "cũ", "ts": (now - timedelta(days=120)).isoformat()})
    store.put(("researcher", "memory"), "fresh",
              {"fact": "mới", "ts": now.isoformat()})

    deleted = run_retention_sweep(now=now)

    assert deleted.get("memory_facts") == 1
    remaining = [i.value["fact"] for i in store.search(("researcher", "memory"), limit=10)]
    assert remaining == ["mới"]
