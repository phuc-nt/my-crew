"""v76 phase 3: autonomy bands — store fail direction, the review gate as the ONLY
effect, the asymmetric closed loop, and the autonomy invariants as source-level pins."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from my_crew.runtime.band_store import (
    BAND_NORMAL,
    BAND_SUPERVISED,
    BAND_TRUSTED,
    BandStore,
    band_for,
)


def _patch_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.config.settings.DATA_DIR", tmp_path)


# --- store fail direction ------------------------------------------------------------


def test_no_store_file_means_normal_and_no_side_effect(monkeypatch, tmp_path):
    _patch_data_dir(monkeypatch, tmp_path)
    assert band_for("researcher") == BAND_NORMAL
    assert not (tmp_path / "agent_bands.sqlite3").exists()  # read never creates


def test_broken_store_means_supervised(monkeypatch, tmp_path):
    _patch_data_dir(monkeypatch, tmp_path)
    (tmp_path / "agent_bands.sqlite3").write_text("not a database")
    assert band_for("researcher") == BAND_SUPERVISED  # fail-strict, never trust-more


def test_set_and_get_roundtrip(monkeypatch, tmp_path):
    _patch_data_dir(monkeypatch, tmp_path)
    store = BandStore()
    store.set("researcher", BAND_SUPERVISED, reason="test", changed_by="ceo")
    store.close()
    assert band_for("researcher") == BAND_SUPERVISED


# --- the review gate is the only effect ----------------------------------------------


def _task(steps):
    return SimpleNamespace(steps=steps)


def _step(step_id, assigned_to="agent-a", needs_review=False, deps=(),
          external_write=False):
    return SimpleNamespace(step_id=step_id, assigned_to=assigned_to,
                           needs_review=needs_review, deps=tuple(deps),
                           external_write=external_write)


def test_supervised_forces_review_even_when_plan_waived(monkeypatch, tmp_path):
    from my_crew.agent.coordinator_nodes.review_insert import effective_needs_review

    _patch_data_dir(monkeypatch, tmp_path)
    store = BandStore()
    store.set("agent-a", BAND_SUPERVISED, reason="t", changed_by="ceo")
    store.close()
    s1 = _step("s1", needs_review=False)
    assert effective_needs_review(_task([s1]), s1) is True


def test_trusted_waives_ordinary_but_never_terminal_or_external(monkeypatch, tmp_path):
    from my_crew.agent.coordinator_nodes.review_insert import effective_needs_review

    _patch_data_dir(monkeypatch, tmp_path)
    store = BandStore()
    store.set("agent-a", BAND_TRUSTED, reason="t", changed_by="ceo")
    store.close()
    mid = _step("mid", needs_review=True)
    terminal = _step("final", needs_review=True, deps=("mid",))
    task = _task([mid, terminal])
    assert effective_needs_review(task, mid) is False  # ordinary step waived
    assert effective_needs_review(task, terminal) is True  # terminal always reviewed
    ext = _step("ext", needs_review=True, external_write=True)
    task2 = _task([ext, _step("z", deps=("ext",))])
    assert effective_needs_review(task2, ext) is True  # external write always reviewed


def test_normal_band_keeps_plan_flag_byte_identical(monkeypatch, tmp_path):
    from my_crew.agent.coordinator_nodes.review_insert import effective_needs_review

    _patch_data_dir(monkeypatch, tmp_path)
    s1 = _step("s1", needs_review=True)
    s0 = _step("s0", needs_review=False)
    assert effective_needs_review(_task([s1]), s1) is True
    assert effective_needs_review(_task([s0]), s0) is False


# --- closed loop: asymmetric, evidence-gated -----------------------------------------


def _metrics(agents):
    return {"window_days": 14, "agents": agents}


def _agent(nd_value, ci, n=20):
    return {"tentative": n < 5,
            "needs_decision_rate": {"value": nd_value, "ci": ci, "n": n}}


def _run_loop(monkeypatch, tmp_path, agents):
    _patch_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr("my_crew.runtime.agent_metrics.agent_metrics",
                        lambda window_days=14: _metrics(agents))
    notices = []
    monkeypatch.setattr("my_crew.runtime.band_loop._announce",
                        lambda aid, milestone, message: notices.append((aid, milestone)))
    from my_crew.runtime.band_loop import run_band_loop

    changed = run_band_loop(force=True)
    return changed, notices


def test_loop_demotes_clear_outlier_and_proposes_ambiguous(monkeypatch, tmp_path):
    agents = {
        "good-1": _agent(0.05, (0.02, 0.12)),
        "good-2": _agent(0.08, (0.03, 0.15)),
        "good-3": _agent(0.10, (0.05, 0.18)),
        "mid": _agent(0.30, (0.05, 0.5)),  # >= p75 but CI-low below median → propose
        "bad": _agent(0.60, (0.45, 0.72)),  # >= p90 AND CI-low > median → demote
    }
    changed, notices = _run_loop(monkeypatch, tmp_path, agents)
    assert changed == 1
    assert band_for("bad") == BAND_SUPERVISED
    assert band_for("mid") == BAND_NORMAL  # proposal only, nothing changed
    kinds = dict((aid, m) for aid, m in notices)
    assert kinds.get("bad") == "band_demoted"
    assert kinds.get("mid") == "band_demote_proposed"


def test_loop_never_acts_on_tentative_or_tiny_fleet(monkeypatch, tmp_path):
    changed, notices = _run_loop(monkeypatch, tmp_path, {
        "a": _agent(0.9, (0.7, 0.97), n=2),  # tentative — excluded entirely
        "b": _agent(0.05, (0.01, 0.1)),
        "c": _agent(0.06, (0.02, 0.12)),
    })
    assert changed == 0 and notices == []  # fleet < MIN_FLEET after exclusion


def test_loop_auto_promotes_recovered_supervised_agent(monkeypatch, tmp_path):
    _patch_data_dir(monkeypatch, tmp_path)
    store = BandStore()
    store.set("healed", BAND_SUPERVISED, reason="old demote", changed_by="band-loop")
    # backdate past the cooldown window
    store._conn.execute("UPDATE agent_bands SET updated_at='2020-01-01T00:00:00+00:00'")
    store._conn.commit()
    store.close()
    agents = {
        "healed": _agent(0.02, (0.005, 0.08)),  # CI-high below fleet median
        "x": _agent(0.2, (0.1, 0.3)),
        "y": _agent(0.25, (0.15, 0.35)),
        "z": _agent(0.3, (0.2, 0.4)),
    }
    changed, notices = _run_loop(monkeypatch, tmp_path, agents)
    assert band_for("healed") == BAND_NORMAL
    assert ("healed", "band_promoted") in notices


def test_loop_respects_cooldown(monkeypatch, tmp_path):
    _patch_data_dir(monkeypatch, tmp_path)
    store = BandStore()
    store.set("bad", BAND_NORMAL, reason="fresh change", changed_by="ceo")
    store.close()
    agents = {
        "good-1": _agent(0.05, (0.02, 0.12)),
        "good-2": _agent(0.08, (0.03, 0.15)),
        "good-3": _agent(0.10, (0.05, 0.18)),
        "bad": _agent(0.60, (0.45, 0.72)),
    }
    changed, _ = _run_loop(monkeypatch, tmp_path, agents)
    assert changed == 0  # changed 5 minutes ago → cooldown holds


# --- autonomy invariants: source-level pins ------------------------------------------


def test_band_never_reaches_dispatch_gateway_or_budget_paths():
    """Plan invariant as a test: the ONLY runtime consumer of band_for is the review
    gate. If band ever leaks into dispatch/routing/gateway/budget code, this fails."""
    root = Path("my_crew")
    forbidden = [
        root / "agent" / "coordinator_nodes" / "tick_actions.py",
        root / "runtime_backends" / "protocol.py",
        root / "actions" / "action_gateway.py",
        root / "runtime" / "team_task_cost.py",
        root / "runtime" / "autopilot_sweep.py",
        root / "runtime" / "team_step_runner.py",
    ]
    for f in forbidden:
        assert "band_for" not in f.read_text(), f"band leaked into {f}"
    from my_crew.agent.coordinator_nodes import review_insert

    assert hasattr(review_insert, "effective_needs_review")  # the one sanctioned seam
