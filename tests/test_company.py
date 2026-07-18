"""company.yaml loader/writer — greenfield, degrade-not-raise."""

from __future__ import annotations

import pytest

from my_crew.runtime.company import (
    DEFAULT_TEAM_TASK_CAP_USD,
    Company,
    load_company,
    save_company,
)


def test_missing_file_returns_safe_default(tmp_path):
    c = load_company(tmp_path / "nope.yaml")
    assert c == Company(name="", coordinator_id=None, team_task_cap_usd=DEFAULT_TEAM_TASK_CAP_USD)


def test_round_trip(tmp_path):
    p = tmp_path / "company.yaml"
    save_company("Acme Corp", "coord-1", 5.0, path=p)
    assert load_company(p) == Company(
        name="Acme Corp", coordinator_id="coord-1", team_task_cap_usd=5.0
    )


def test_round_trip_default_cap(tmp_path):
    p = tmp_path / "company.yaml"
    save_company("Acme", None, path=p)
    c = load_company(p)
    assert c.name == "Acme"
    assert c.coordinator_id is None
    assert c.team_task_cap_usd == DEFAULT_TEAM_TASK_CAP_USD


def test_malformed_yaml_degrades(tmp_path):
    p = tmp_path / "company.yaml"
    p.write_text("not: [valid: yaml: at all\n", encoding="utf-8")
    c = load_company(p)
    assert c == Company(name="", coordinator_id=None, team_task_cap_usd=DEFAULT_TEAM_TASK_CAP_USD)


def test_non_mapping_yaml_degrades(tmp_path):
    p = tmp_path / "company.yaml"
    p.write_text("- just\n- a\n- list\n", encoding="utf-8")
    c = load_company(p)
    assert c == Company(name="", coordinator_id=None, team_task_cap_usd=DEFAULT_TEAM_TASK_CAP_USD)


def test_bad_cap_degrades_to_default(tmp_path):
    p = tmp_path / "company.yaml"
    p.write_text(
        "name: Acme\ncoordinator_id: null\nteam_task_cap_usd: notanumber\n", encoding="utf-8"
    )
    c = load_company(p)
    assert c.team_task_cap_usd == DEFAULT_TEAM_TASK_CAP_USD


def test_blank_coordinator_becomes_none(tmp_path):
    p = tmp_path / "company.yaml"
    p.write_text("name: Acme\ncoordinator_id: ''\n", encoding="utf-8")
    assert load_company(p).coordinator_id is None


def test_atomic_write_leaves_no_tmp_file(tmp_path):
    p = tmp_path / "company.yaml"
    save_company("Acme", "coord-1", path=p)
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


def test_committed_company_yaml_loads():
    # The real repo-root company.yaml is greenfield-empty until someone runs Setup.
    c = load_company()
    assert isinstance(c, Company)
    assert c.team_task_cap_usd == DEFAULT_TEAM_TASK_CAP_USD


@pytest.mark.parametrize("cap", [0.0, -1.0])
def test_save_accepts_any_float_validation_is_at_route_layer(tmp_path, cap):
    # company.py itself does not enforce cap > 0 — that's a route-layer 400 (see
    # routes_company.py); the loader/writer just round-trips whatever float it's given.
    p = tmp_path / "company.yaml"
    save_company("Acme", None, cap, path=p)
    assert load_company(p).team_task_cap_usd == cap
