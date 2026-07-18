"""Slice 1: mpm agent list + register against tmp registry/profiles (offline)."""

from __future__ import annotations

import shutil
from pathlib import Path

from my_crew.entrypoints.mpm_registry_cmds import run_list, run_register
from my_crew.runtime.registry import load_registry

_REAL_DEFAULT = Path("profiles/default/profile.yaml")


def _seed(tmp_path, registry_text="agents:\n  - id: default\n    enabled: true\n"):
    """Build a tmp profiles/ (with default/) + a tmp registry.yaml; return (pdir, reg)."""
    pdir = tmp_path / "profiles"
    (pdir / "default").mkdir(parents=True)
    shutil.copyfile(_REAL_DEFAULT, pdir / "default" / "profile.yaml")
    (pdir / "default" / "SOUL.md").write_text("<!-- x -->\n", encoding="utf-8")
    reg = tmp_path / "registry.yaml"
    reg.write_text("# comment line\n" + registry_text, encoding="utf-8")
    return pdir, reg


# --- register ---


def test_register_scaffolds_and_appends(tmp_path):
    pdir, reg = _seed(tmp_path)
    rc = run_register(["acme"], registry_path=reg, profiles_dir=pdir)
    assert rc == 0
    assert (pdir / "acme" / "profile.yaml").exists()
    for md in ("SOUL.md", "PROJECT.md", "MEMORY.md"):
        assert (pdir / "acme" / md).exists()
    # the comment + default survived; acme is now in the registry
    text = reg.read_text(encoding="utf-8")
    assert "# comment line" in text and "id: default" in text
    ids = [e.id for e in load_registry(reg)]
    assert ids == ["default", "acme"]


def test_register_idempotent_second_errors(tmp_path):
    pdir, reg = _seed(tmp_path)
    run_register(["acme"], registry_path=reg, profiles_dir=pdir)
    before = reg.read_text(encoding="utf-8")
    rc = run_register(["acme"], registry_path=reg, profiles_dir=pdir)
    assert rc == 1
    assert reg.read_text(encoding="utf-8") == before  # no further append


def test_register_bad_id_no_writes(tmp_path, capsys):
    pdir, reg = _seed(tmp_path)
    before = reg.read_text(encoding="utf-8")
    rc = run_register(["../x"], registry_path=reg, profiles_dir=pdir)
    assert rc == 2
    assert "Invalid agent id" in capsys.readouterr().err
    assert reg.read_text(encoding="utf-8") == before  # registry untouched
    assert not (pdir / "../x").exists()


def test_register_no_id_usage_exit_2(tmp_path, capsys):
    pdir, reg = _seed(tmp_path)
    rc = run_register([], registry_path=reg, profiles_dir=pdir)
    assert rc == 2
    assert "usage:" in capsys.readouterr().err


def test_register_collision_in_registry_only(tmp_path, capsys):
    # beta is in the registry but has no profile dir → still a collision.
    pdir, reg = _seed(tmp_path, "agents:\n  - id: default\n  - id: beta\n")
    rc = run_register(["beta"], registry_path=reg, profiles_dir=pdir)
    assert rc == 1
    assert "already in the registry" in capsys.readouterr().err


# --- list ---


def test_list_shows_rows_with_last_run(tmp_path, monkeypatch, capsys):
    pdir, reg = _seed(tmp_path, "agents:\n  - id: default\n  - id: acme\n")
    (pdir / "acme").mkdir()
    shutil.copyfile(_REAL_DEFAULT, pdir / "acme" / "profile.yaml")
    # seed a runs.jsonl for acme under a tmp data dir
    monkeypatch.setattr("my_crew.runtime.agent_paths.DATA_DIR", tmp_path / ".data")
    acme_dir = tmp_path / ".data" / "agents" / "acme"
    acme_dir.mkdir(parents=True)
    (acme_dir / "runs.jsonl").write_text(
        '{"kind":"daily","status":"delivered","ts":"2026-06-24T08:00:00+00:00"}\n',
        encoding="utf-8",
    )
    rc = run_list([], registry_path=reg, profiles_dir=pdir)
    assert rc == 0
    out = capsys.readouterr().out
    assert "acme" in out and "daily delivered" in out
    assert "default" in out and "never run" in out  # default has no runs.jsonl


def test_list_missing_profile_is_error_row_not_crash(tmp_path, monkeypatch, capsys):
    pdir, reg = _seed(tmp_path, "agents:\n  - id: ghost\n")  # no profiles/ghost/
    monkeypatch.setattr("my_crew.runtime.agent_paths.DATA_DIR", tmp_path / ".data")
    rc = run_list([], registry_path=reg, profiles_dir=pdir)
    assert rc == 0
    assert "ghost" in capsys.readouterr().out  # error row, no traceback


def test_list_empty_registry(tmp_path, capsys):
    reg = tmp_path / "registry.yaml"
    reg.write_text("agents: []\n", encoding="utf-8")
    assert run_list([], registry_path=reg) == 0
    assert "no agents registered" in capsys.readouterr().out
