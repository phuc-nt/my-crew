"""First-run seeding of MY_CREW_HOME (installed/container mode): atomic, copy-if-absent.

Only `default` seeds — template consumers all read SHIPPED_ROOT directly, so a home
copy of templates would be dead data (review M2).
"""

from __future__ import annotations

from my_crew.config import home_seed


def _make_shipped(root):
    for name in ("default", "templates"):
        d = root / "profiles" / name
        d.mkdir(parents=True)
        (d / "profile.yaml").write_text(f"id: {name}\n", encoding="utf-8")
    return root


def test_checkout_mode_is_noop(monkeypatch, tmp_path):
    shipped = _make_shipped(tmp_path)
    monkeypatch.setattr(home_seed, "SHIPPED_ROOT", shipped)
    monkeypatch.setattr(home_seed, "MY_CREW_HOME", shipped)  # checkout: same root
    home_seed.ensure_home_seeded()
    assert sorted(p.name for p in (shipped / "profiles").iterdir()) == ["default", "templates"]


def test_installed_mode_seeds_default_only(monkeypatch, tmp_path):
    shipped = _make_shipped(tmp_path / "app")
    home = tmp_path / "home"
    monkeypatch.setattr(home_seed, "SHIPPED_ROOT", shipped)
    monkeypatch.setattr(home_seed, "MY_CREW_HOME", home)
    home_seed.ensure_home_seeded()
    assert (home / "profiles" / "default" / "profile.yaml").exists()
    # templates are read from SHIPPED_ROOT everywhere — never copied into home
    assert not (home / "profiles" / "templates").exists()
    # no temp dir left behind
    assert not (home / "profiles" / "default.seeding").exists()


def test_seeding_never_overwrites_user_edits(monkeypatch, tmp_path):
    shipped = _make_shipped(tmp_path / "app")
    home = tmp_path / "home"
    user_profile = home / "profiles" / "default"
    user_profile.mkdir(parents=True)
    (user_profile / "profile.yaml").write_text("id: default\nedited: true\n", encoding="utf-8")
    monkeypatch.setattr(home_seed, "SHIPPED_ROOT", shipped)
    monkeypatch.setattr(home_seed, "MY_CREW_HOME", home)
    home_seed.ensure_home_seeded()
    assert "edited: true" in (user_profile / "profile.yaml").read_text(encoding="utf-8")


def test_interrupted_seed_leftover_tmp_is_recovered(monkeypatch, tmp_path):
    """A crash mid-copy leaves only the temp dir — the next boot must still seed."""
    shipped = _make_shipped(tmp_path / "app")
    home = tmp_path / "home"
    leftover = home / "profiles" / "default.seeding"
    leftover.mkdir(parents=True)
    (leftover / "partial.yaml").write_text("truncated", encoding="utf-8")
    monkeypatch.setattr(home_seed, "SHIPPED_ROOT", shipped)
    monkeypatch.setattr(home_seed, "MY_CREW_HOME", home)
    home_seed.ensure_home_seeded()
    assert (home / "profiles" / "default" / "profile.yaml").exists()
    assert not leftover.exists()
    assert not (home / "profiles" / "default" / "partial.yaml").exists()
