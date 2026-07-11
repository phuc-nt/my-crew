"""v19 Phase 1: memory provider seam.

Covers: `memory:` parse (default static, kioku deferred, unknown fail-loud with RuntimeError
not ValueError), static provider byte-identity, and that `resolve_memory_text` is what the
six prompt sites now use.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.memory.provider import (
    MemoryConfig,
    parse_memory_config,
    resolve_memory_text,
)
from src.memory.static_provider import StaticMemoryProvider
from src.profile.loader import load_profile


def _write_profile(tmp_path: Path, agent_id: str, yaml_body: str, memory_md: str = "") -> Path:
    d = tmp_path / agent_id
    d.mkdir(parents=True)
    (d / "profile.yaml").write_text(textwrap.dedent(yaml_body), encoding="utf-8")
    if memory_md:
        (d / "MEMORY.md").write_text(memory_md, encoding="utf-8")
    return d


# --- parse_memory_config -------------------------------------------------------------


def test_absent_memory_block_defaults_static():
    assert parse_memory_config(None) == MemoryConfig(provider="static")
    assert parse_memory_config({}) == MemoryConfig(provider="static")
    assert parse_memory_config("") == MemoryConfig(provider="static")


def test_explicit_static():
    assert parse_memory_config({"provider": "static"}).provider == "static"


def test_kioku_parses_but_is_deferred_at_resolve():
    # Parsing kioku is allowed (an operator may opt in); resolving it raises (v19.5).
    assert parse_memory_config({"provider": "kioku"}).provider == "kioku"


def test_unknown_provider_raises_runtimeerror():
    # Must be RuntimeError (not ValueError) so it does not escape the entrypoint catch.
    with pytest.raises(RuntimeError, match="unknown provider"):
        parse_memory_config({"provider": "redis"})


def test_non_mapping_memory_block_raises_runtimeerror():
    with pytest.raises(RuntimeError, match="must be a mapping"):
        parse_memory_config(["static"])


# --- resolve_memory_text -------------------------------------------------------------


def test_static_resolves_to_memory_md_verbatim(tmp_path):
    _write_profile(
        tmp_path,
        "a1",
        "name: A1\n",
        memory_md="Ghi nhớ: khách X thích tông trang trọng.\n",
    )
    loaded = load_profile("a1", profiles_dir=tmp_path, data_dir=tmp_path / ".data")
    assert loaded.memory_config.provider == "static"
    assert resolve_memory_text(loaded) == "Ghi nhớ: khách X thích tông trang trọng.\n"
    # Byte-identical to the raw MEMORY.md field.
    assert resolve_memory_text(loaded) == loaded.memory


def test_static_provider_load_context_matches_field(tmp_path):
    _write_profile(tmp_path, "a2", "name: A2\n", memory_md="fact\n")
    loaded = load_profile("a2", profiles_dir=tmp_path, data_dir=tmp_path / ".data")
    assert StaticMemoryProvider().load_context(loaded) == loaded.memory


def test_static_provider_record_is_noop(tmp_path):
    _write_profile(tmp_path, "a3", "name: A3\n", memory_md="fact\n")
    loaded = load_profile("a3", profiles_dir=tmp_path, data_dir=tmp_path / ".data")
    # No exception, no mutation of the on-disk MEMORY.md.
    StaticMemoryProvider().record(loaded, "new fact")
    assert (tmp_path / "a3" / "MEMORY.md").read_text(encoding="utf-8") == "fact\n"


def test_kioku_provider_deferred_raises_runtimeerror(tmp_path):
    _write_profile(tmp_path, "a4", "name: A4\nmemory:\n  provider: kioku\n")
    loaded = load_profile("a4", profiles_dir=tmp_path, data_dir=tmp_path / ".data")
    with pytest.raises(RuntimeError, match="v19.5"):
        resolve_memory_text(loaded)


def test_loader_threads_memory_config(tmp_path):
    _write_profile(tmp_path, "a5", "name: A5\nmemory:\n  provider: static\n")
    loaded = load_profile("a5", profiles_dir=tmp_path, data_dir=tmp_path / ".data")
    assert isinstance(loaded.memory_config, MemoryConfig)
    assert loaded.memory_config.provider == "static"


def test_loader_bad_memory_block_raises_runtimeerror(tmp_path):
    _write_profile(tmp_path, "a6", "name: A6\nmemory:\n  provider: bogus\n")
    with pytest.raises(RuntimeError, match="unknown provider"):
        load_profile("a6", profiles_dir=tmp_path, data_dir=tmp_path / ".data")
