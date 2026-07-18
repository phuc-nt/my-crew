"""Slice 1: mpm top-level dispatch grammar (no I/O)."""

from __future__ import annotations

from my_crew.entrypoints import mpm


def test_no_args_usage_exit_2(capsys):
    assert mpm.main([]) == 2
    assert "usage:" in capsys.readouterr().err


def test_agent_alone_exit_2(capsys):
    assert mpm.main(["agent"]) == 2
    assert "usage:" in capsys.readouterr().err


def test_non_agent_top_level_exit_2(capsys):
    assert mpm.main(["bogus", "list"]) == 2


def test_unknown_subcommand_exit_2(capsys):
    assert mpm.main(["agent", "bogus"]) == 2
    assert "unknown subcommand" in capsys.readouterr().err


def _spy(seen):
    def _fn(rest):
        seen["called"] = rest
        return 0

    return _fn


def test_list_routes_to_run_list(monkeypatch):
    import my_crew.entrypoints.mpm_registry_cmds as cmds

    seen = {}
    monkeypatch.setattr(cmds, "run_list", _spy(seen))
    assert mpm.main(["agent", "list"]) == 0
    assert seen["called"] == []


def test_register_routes_to_run_register(monkeypatch):
    import my_crew.entrypoints.mpm_registry_cmds as cmds

    seen = {}
    monkeypatch.setattr(cmds, "run_register", _spy(seen))
    assert mpm.main(["agent", "register", "acme"]) == 0
    assert seen["called"] == ["acme"]
