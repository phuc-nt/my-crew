"""v38 #2: skill curator — usage-tracking + auto-archive.

record_usage bumps a per-agent counter (best-effort, never breaks selection); the archive
sweep moves an agent-OWN skill unused past the threshold into skills/.archive/ — never
deleting, never touching template-role skills. Pure internal state, no gateway/egress.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from my_crew.skills.skill_curator import (
    ARCHIVE_UNUSED_DAYS,
    NEVER_USED_GRACE_DAYS,
    archive_agent_skills,
    record_usage,
)

_NOW = datetime(2026, 7, 13, 3, 0, 0)


@pytest.fixture
def agent_world(tmp_path, monkeypatch):
    """Isolated per-agent data dir + profiles dir so usage/archive touch only tmp."""
    monkeypatch.setattr("my_crew.runtime.agent_paths.agent_data_dir",
                        lambda aid: tmp_path / "data" / aid)
    monkeypatch.setattr("my_crew.packs.registry._PROFILES_DIR", tmp_path / "profiles",
                        raising=False)
    (tmp_path / "profiles" / "a1" / "skills").mkdir(parents=True)
    return tmp_path


def _write_skill(world, agent_id, name, *, mtime: datetime | None = None):
    import os

    f = world / "profiles" / agent_id / "skills" / f"{name}.md"
    f.write_text(f"---\nname: {name}\ndescription: d\n---\nthan", encoding="utf-8")
    if mtime:
        ts = mtime.timestamp()
        os.utime(f, (ts, ts))
    return f


def test_record_usage_bumps_count_and_last_used(agent_world):
    record_usage("a1", ["tra-cuu", "tom-tat"], now=_NOW)
    record_usage("a1", ["tra-cuu"], now=_NOW + timedelta(hours=1))
    import json
    usage = json.loads((agent_world / "data" / "a1" / "skill_usage.json").read_text())
    assert usage["tra-cuu"]["count"] == 2
    assert usage["tom-tat"]["count"] == 1
    assert usage["tra-cuu"]["last_used"] > usage["tom-tat"]["last_used"]


def test_record_usage_empty_is_noop(agent_world):
    record_usage("a1", [], now=_NOW)
    record_usage("a1", None, now=_NOW)
    assert not (agent_world / "data" / "a1" / "skill_usage.json").exists()


def test_record_usage_never_raises_on_bad_dir(monkeypatch):
    # Point at an unwritable path shape; must swallow, never raise into the hot path.
    monkeypatch.setattr("my_crew.runtime.agent_paths.agent_data_dir",
                        lambda aid: (_ for _ in ()).throw(OSError("boom")))
    record_usage("a1", ["x"], now=_NOW)  # no exception


def test_archive_moves_unused_skill(agent_world):
    _write_skill(agent_world, "a1", "stale")
    record_usage("a1", ["stale"], now=_NOW - timedelta(days=ARCHIVE_UNUSED_DAYS + 5))
    archived = archive_agent_skills("a1", now=_NOW, profiles_dir=agent_world / "profiles")
    assert archived == ["stale"]
    skills_dir = agent_world / "profiles" / "a1" / "skills"
    assert not (skills_dir / "stale.md").exists()  # moved
    assert (skills_dir / ".archive" / "stale.md").exists()  # not deleted


def test_archive_keeps_recently_used(agent_world):
    _write_skill(agent_world, "a1", "fresh")
    record_usage("a1", ["fresh"], now=_NOW - timedelta(days=5))
    archived = archive_agent_skills("a1", now=_NOW, profiles_dir=agent_world / "profiles")
    assert archived == []
    assert (agent_world / "profiles" / "a1" / "skills" / "fresh.md").exists()


def test_never_used_archived_only_after_grace(agent_world):
    # A never-used skill younger than the grace window stays.
    _write_skill(agent_world, "a1", "young", mtime=_NOW - timedelta(days=5))
    assert archive_agent_skills("a1", now=_NOW, profiles_dir=agent_world / "profiles") == []
    # Older than grace → archived.
    _write_skill(agent_world, "a1", "old", mtime=_NOW - timedelta(days=NEVER_USED_GRACE_DAYS + 5))
    assert "old" in archive_agent_skills("a1", now=_NOW, profiles_dir=agent_world / "profiles")


def test_archive_never_touches_template_skills(agent_world):
    # Template-role skills live under profiles/templates/, NOT the agent dir — the sweep
    # only scans profiles/<id>/skills/, so template skills are out of scope by construction.
    tmpl = agent_world / "profiles" / "templates" / "role1" / "skills"
    tmpl.mkdir(parents=True)
    (tmpl / "shared.md").write_text("---\nname: shared\ndescription: d\n---\nx", encoding="utf-8")
    archive_agent_skills("a1", now=_NOW, profiles_dir=agent_world / "profiles")
    assert (tmpl / "shared.md").exists()  # untouched


def test_select_skill_text_records_when_context_has_agent_id(agent_world):
    from my_crew.profile.context import ProfileContext
    from my_crew.skills.models import Skill
    from my_crew.skills.skill_selector import select_skill_text

    skill = Skill(name="s1", description="d", body="body")
    ctx = ProfileContext(
        skills=(skill,), skill_selector=lambda cands, kind: ["s1"], agent_id="a1",
    )
    out = select_skill_text(ctx, "internal", kind="daily")
    assert "body" in out  # selection still works
    import json
    usage = json.loads((agent_world / "data" / "a1" / "skill_usage.json").read_text())
    assert usage["s1"]["count"] == 1


def test_select_skill_text_no_agent_id_no_tracking(agent_world):
    from my_crew.profile.context import ProfileContext
    from my_crew.skills.models import Skill
    from my_crew.skills.skill_selector import select_skill_text

    ctx = ProfileContext(skills=(Skill(name="s1", description="d", body="b"),),
                         skill_selector=lambda c, k: ["s1"])  # no agent_id
    select_skill_text(ctx, "internal", kind="daily")
    assert not (agent_world / "data" / "a1" / "skill_usage.json").exists()


def test_sweep_cooldown_skips_repeat_within_window(agent_world, monkeypatch):
    """Review MED #4: the 60s tick fires the sweep ~60x in the hour-3 window; a per-agent
    cooldown makes all but the first a no-op."""
    from my_crew.skills import skill_curator

    class _E:
        id = "a1"
        enabled = True

    monkeypatch.setattr("my_crew.runtime.registry.load_registry", lambda: (_E(),))
    calls = []
    monkeypatch.setattr(skill_curator, "archive_agent_skills",
                        lambda aid, now=None: calls.append(aid) or [])
    skill_curator.run_skill_archive_sweep(now=_NOW)
    skill_curator.run_skill_archive_sweep(now=_NOW + timedelta(minutes=1))  # cooldown
    assert calls == ["a1"]  # only the first ran
    skill_curator.run_skill_archive_sweep(now=_NOW + timedelta(hours=25))  # cooldown expired
    assert calls == ["a1", "a1"]


def test_service_gate_only_fires_at_sweep_hour(monkeypatch):
    from my_crew.runtime import service

    calls = []
    monkeypatch.setattr("my_crew.skills.skill_curator.run_skill_archive_sweep",
                        lambda now=None: calls.append(now) or 0)
    service._archive_stale_skills_best_effort(datetime(2026, 7, 13, 14, 0))
    assert calls == []
    service._archive_stale_skills_best_effort(datetime(2026, 7, 13, 3, 5))
    assert len(calls) == 1
    monkeypatch.setattr("my_crew.skills.skill_curator.run_skill_archive_sweep",
                        lambda now=None: (_ for _ in ()).throw(RuntimeError("boom")))
    service._archive_stale_skills_best_effort(datetime(2026, 7, 13, 3, 6))  # no raise
