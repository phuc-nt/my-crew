"""MY_CREW_HOME resolution order: env > git checkout > ~/.my-crew (settings.resolve_home)."""

from __future__ import annotations

from pathlib import Path

from my_crew.config.settings import DATA_DIR, MY_CREW_HOME, resolve_home


def test_env_value_wins_over_checkout(tmp_path):
    (tmp_path / ".git").mkdir()
    target = tmp_path / "elsewhere"
    assert resolve_home(str(target), tmp_path) == target


def test_env_value_expands_user():
    assert resolve_home("~/crew-home", Path("/nonexistent")) == Path.home() / "crew-home"


def test_checkout_keeps_repo_local_state(tmp_path):
    (tmp_path / ".git").mkdir()
    assert resolve_home(None, tmp_path) == tmp_path


def test_installed_package_falls_back_to_home_dir(tmp_path):
    # No .git next to the package (site-packages install) → user state must not
    # land inside the install dir.
    assert resolve_home(None, tmp_path) == Path.home() / ".my-crew"


def test_empty_env_value_is_ignored(tmp_path):
    (tmp_path / ".git").mkdir()
    assert resolve_home("", tmp_path) == tmp_path


def test_module_constants_are_consistent():
    # This suite runs from a git checkout, so module-level state stays repo-local
    # (the pre-seam behavior) and .data hangs off the resolved home.
    assert DATA_DIR == MY_CREW_HOME / ".data"
    assert (MY_CREW_HOME / ".git").exists()
