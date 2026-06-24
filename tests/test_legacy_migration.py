"""Slice 1: once-only v1 `.data/` → `.data/agents/default/` migration."""

from __future__ import annotations

import src.runtime.legacy_migration as lm
from src.runtime.legacy_migration import migrate_legacy_data_dir


def _make_legacy(data_dir):
    """Create a fake v1 `.data/` with all 5 stores + an unrelated file."""
    (data_dir / "audit").mkdir(parents=True)
    (data_dir / "audit" / "audit.jsonl").write_text("a\n", encoding="utf-8")
    (data_dir / "budget").mkdir()
    (data_dir / "budget" / "budget-2026-06.json").write_text("{}", encoding="utf-8")
    (data_dir / "checkpoints.db").write_text("ckpt", encoding="utf-8")
    (data_dir / "dedup.db").write_text("dedup", encoding="utf-8")
    (data_dir / "approvals.db").write_text("appr", encoding="utf-8")
    (data_dir / "foo.txt").write_text("unrelated", encoding="utf-8")  # must NOT move


def test_full_move(tmp_path, monkeypatch):
    data_dir = tmp_path / ".data"
    data_dir.mkdir()
    _make_legacy(data_dir)
    monkeypatch.setattr(lm, "DATA_DIR", data_dir)

    assert migrate_legacy_data_dir() is True
    target = data_dir / "agents" / "default"
    # all 5 stores moved under the default agent dir
    assert (target / "audit" / "audit.jsonl").read_text(encoding="utf-8") == "a\n"
    assert (target / "checkpoints.db").exists()
    assert (target / "dedup.db").exists()
    assert (target / "approvals.db").exists()
    assert (target / "budget" / "budget-2026-06.json").exists()
    # top-level copies are gone
    assert not (data_dir / "audit").exists()
    assert not (data_dir / "checkpoints.db").exists()
    # the unrelated file is UNTOUCHED at the top level
    assert (data_dir / "foo.txt").read_text(encoding="utf-8") == "unrelated"
    assert not (target / "foo.txt").exists()


def test_second_call_is_noop(tmp_path, monkeypatch):
    data_dir = tmp_path / ".data"
    data_dir.mkdir()
    _make_legacy(data_dir)
    monkeypatch.setattr(lm, "DATA_DIR", data_dir)

    assert migrate_legacy_data_dir() is True
    assert migrate_legacy_data_dir() is False  # already migrated → no-op
    # nothing further moved; default dir intact
    assert (data_dir / "agents" / "default" / "dedup.db").exists()


def test_fresh_install_is_noop(tmp_path, monkeypatch):
    data_dir = tmp_path / ".data"
    data_dir.mkdir()  # empty: no legacy stores
    monkeypatch.setattr(lm, "DATA_DIR", data_dir)

    assert migrate_legacy_data_dir() is False
    assert not (data_dir / "agents").exists()  # no empty default dir created


def test_existing_target_not_clobbered(tmp_path, monkeypatch):
    # `.data/agents/default/` already exists (e.g. a prior partial run) → the guard
    # returns False and the legacy top-level stores are left untouched.
    data_dir = tmp_path / ".data"
    data_dir.mkdir()
    _make_legacy(data_dir)
    target = data_dir / "agents" / "default"
    target.mkdir(parents=True)
    (target / "dedup.db").write_text("EXISTING", encoding="utf-8")
    monkeypatch.setattr(lm, "DATA_DIR", data_dir)

    assert migrate_legacy_data_dir() is False
    # the existing target file is preserved (not clobbered by the legacy one)
    assert (target / "dedup.db").read_text(encoding="utf-8") == "EXISTING"
    # the legacy top-level dedup.db is left in place (not moved)
    assert (data_dir / "dedup.db").read_text(encoding="utf-8") == "dedup"
