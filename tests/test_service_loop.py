"""Service loop resilience: registry entries must not kill the fleet tick."""

from __future__ import annotations


def test_registry_entry_without_profile_dir_is_skipped_not_fatal(tmp_path, monkeypatch, caplog):
    """A registered id with no profiles/<id>/ dir (shipped example registers `admin`
    before the user creates it) must not crash the fleet loop."""
    import logging

    from my_crew.runtime import service as service_mod

    monkeypatch.setattr(
        service_mod,
        "load_registry",
        lambda: [
            type("E", (), {"id": "ghost", "enabled": True})(),
        ],
    )

    def _raise(profile_id):
        raise FileNotFoundError(f"Profile {profile_id!r} not found")

    monkeypatch.setattr(service_mod, "load_profile", _raise)
    svc = service_mod.Service()
    caplog.set_level(logging.WARNING, logger="my_crew.runtime.service")
    outcomes = svc.run_tick(__import__("datetime").datetime.now())
    assert outcomes == []
    assert "skipping agent 'ghost'" in caplog.text
