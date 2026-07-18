"""v36 P2: template skills load LIVE from the template dir at runtime (no copy).

An agent with `template_role` set pulls its role template's skills/*.md on every run, so
a template edit reaches the agent with no re-scaffold. Agent-own skills of the same name
win (local override); a pack name is never shadowed; a missing template dir degrades to
fewer skills, never a crash. Agents WITHOUT template_role keep old copied-skill behavior.
"""

from __future__ import annotations

import pytest

from my_crew.skills.skill_pool import _load_template_skills, load_skill_pool


@pytest.fixture
def template_world(tmp_path, monkeypatch):
    """A fake repo root with one role template holding a skill, wired into both the
    template loader and the per-agent skills dir resolver."""
    repo = tmp_path
    tdir = repo / "profiles" / "templates" / "vai-thu" / "skills"
    tdir.mkdir(parents=True)
    (tdir / "tra-cuu.md").write_text(
        "---\nname: tra-cuu\ndescription: tra cứu có nguồn\n---\nThân kỹ năng tra cứu.",
        encoding="utf-8",
    )
    monkeypatch.setattr("my_crew.packs.registry.SHIPPED_ROOT", repo)
    # profile_skills_dir(profile_id, profiles_dir=...) — point agent-own dirs under repo too.
    (repo / "profiles" / "agent-x" / "skills").mkdir(parents=True)
    return repo


def test_template_skills_load_live(template_world):
    pool = load_skill_pool((), profile_id="agent-x",
                           profiles_dir=template_world / "profiles", template_role="vai-thu")
    names = {s.name for s in pool}
    assert "tra-cuu" in names  # came from the template dir, not a copy


def test_template_skill_edit_is_reflected(template_world):
    tfile = template_world / "profiles" / "templates" / "vai-thu" / "skills" / "tra-cuu.md"
    pool1 = load_skill_pool((), template_role="vai-thu")
    assert "cũ" not in next(s.body for s in pool1 if s.name == "tra-cuu")
    tfile.write_text(
        "---\nname: tra-cuu\ndescription: d\n---\nNội dung MỚI cũ hơn.", encoding="utf-8")
    pool2 = load_skill_pool((), template_role="vai-thu")
    assert "MỚI" in next(s.body for s in pool2 if s.name == "tra-cuu")  # live, no re-create


def test_agent_own_skill_overrides_template(template_world):
    own = template_world / "profiles" / "agent-x" / "skills" / "tra-cuu.md"
    own.write_text(
        "---\nname: tra-cuu\ndescription: bản riêng\n---\nBản của riêng agent.",
        encoding="utf-8")
    pool = load_skill_pool((), profile_id="agent-x",
                           profiles_dir=template_world / "profiles", template_role="vai-thu")
    matches = [s for s in pool if s.name == "tra-cuu"]
    assert len(matches) == 1  # template copy dropped, only the local one remains
    assert "riêng" in matches[0].body


def test_missing_template_dir_degrades(template_world):
    pool = load_skill_pool((), template_role="khong-ton-tai")
    assert pool == ()  # WARNING logged, no crash


def test_no_template_role_is_byte_identical(template_world):
    # An agent without template_role never pulls template skills — old behavior.
    pool = load_skill_pool((), profile_id="agent-x",
                           profiles_dir=template_world / "profiles")
    assert all(s.name != "tra-cuu" for s in pool)


def test_load_template_skills_helper_direct(template_world):
    skills = _load_template_skills("vai-thu")
    assert set(skills) == {"tra-cuu"}
    assert _load_template_skills("khong- co") == {}
