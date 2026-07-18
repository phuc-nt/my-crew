"""gh CLI adapter: JSON parse, error surfacing (no real gh needed)."""

from __future__ import annotations

import subprocess

import pytest

from my_crew.adapters import cli_adapter


def _fake_completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_parses_json_list(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _fake_completed(stdout='[{"number": 1}]')
    )
    assert cli_adapter.run_gh(["pr", "list", "--json", "number"]) == [{"number": 1}]


def test_empty_output_is_empty_list(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_completed(stdout=""))
    assert cli_adapter.run_gh(["pr", "list"]) == []


def test_nonzero_exit_raises(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _fake_completed(stderr="auth required", returncode=1)
    )
    with pytest.raises(RuntimeError, match="failed"):
        cli_adapter.run_gh(["pr", "list"])


def test_missing_gh_raises(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", _raise)
    with pytest.raises(RuntimeError, match="not installed"):
        cli_adapter.run_gh(["pr", "list"])


def test_non_json_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_completed(stdout="not json"))
    with pytest.raises(RuntimeError, match="non-JSON"):
        cli_adapter.run_gh(["pr", "list", "--json", "x"])
