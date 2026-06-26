"""M3-P10 Slice 1: skill loader + profile `skills:` block (offline, file IO only)."""

from __future__ import annotations

from src.skills.skill_loader import load_skills

_BUNDLED = {"flag-risk", "prioritize-blockers", "estimate-effort",
            "fetch-jira-epics", "parse-github-labels"}


def test_load_bundled_skills_returns_five():
    skills = load_skills()  # the real committed skills/ dir
    assert {s.name for s in skills} == _BUNDLED
    assert [s.name for s in skills] == sorted(s.name for s in skills)  # deterministic order


def test_skill_frontmatter_parsed():
    skills = {s.name: s for s in load_skills()}
    fr = skills["flag-risk"]
    assert fr.description  # non-empty
    assert "daily" in fr.applies_to and "weekly" in fr.applies_to
    assert fr.body  # markdown body present
    assert "---" not in fr.body  # frontmatter stripped from the body


def test_allowed_tools_parsed_but_ignored(tmp_path):
    # A skill carrying allowed-tools loads fine; the Skill has NO authority field.
    (tmp_path / "x.md").write_text(
        "---\nname: x\ndescription: d\nallowed-tools: [post_message]\n---\nbody", encoding="utf-8"
    )
    s = load_skills(tmp_path)[0]
    assert s.name == "x"
    assert not hasattr(s, "allowed_tools")  # forward-compat: parsed, never an authority field


def test_malformed_skill_skipped(tmp_path):
    (tmp_path / "good.md").write_text("---\nname: g\ndescription: d\n---\nbody", encoding="utf-8")
    (tmp_path / "no-front.md").write_text("just markdown, no frontmatter", encoding="utf-8")
    (tmp_path / "no-name.md").write_text("---\ndescription: d\n---\nbody", encoding="utf-8")
    (tmp_path / "bad-yaml.md").write_text("---\nname: : : oops\n---\nbody", encoding="utf-8")
    names = {s.name for s in load_skills(tmp_path)}
    assert names == {"g"}  # only the good one; the 3 bad ones skipped, no raise


def test_missing_dir_returns_empty(tmp_path):
    assert load_skills(tmp_path / "nope") == []


def test_duplicate_name_deduped_first_wins(tmp_path):
    # Two files, same `name`: the first by filename order wins, the later one is dropped.
    (tmp_path / "a.md").write_text("---\nname: dup\ndescription: d\n---\nFIRST", encoding="utf-8")
    (tmp_path / "b.md").write_text("---\nname: dup\ndescription: d\n---\nSECOND", encoding="utf-8")
    skills = load_skills(tmp_path)
    assert [s.name for s in skills] == ["dup"]  # only one survives
    assert skills[0].body == "FIRST"  # a.md (sorted first) wins


def test_markdown_hr_in_body_not_corrupted(tmp_path):
    # A body containing a markdown horizontal rule (---) must not break parsing: only the
    # FIRST close fence ends the frontmatter; later --- lines stay in the body.
    (tmp_path / "hr.md").write_text(
        "---\nname: hr\ndescription: d\n---\nintro\n\n---\n\nafter the rule", encoding="utf-8"
    )
    s = load_skills(tmp_path)[0]
    assert s.name == "hr" and s.description == "d"
    assert "intro" in s.body and "after the rule" in s.body
    assert "---" in s.body  # the HR is preserved in the body, frontmatter not re-split


# --- profile `skills:` block → LoadedProfile.skills ---


def _write_profile(tmp_path, agent_id, yaml_text):
    d = tmp_path / "profiles" / agent_id
    d.mkdir(parents=True)
    (d / "profile.yaml").write_text(yaml_text, encoding="utf-8")
    return tmp_path / "profiles"


def test_profile_skills_block_parsed(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    from src.profile.loader import load_profile

    base = _write_profile(tmp_path, "acme", "name: Acme\nskills: [flag-risk, estimate-effort]\n")
    lp = load_profile("acme", profiles_dir=base, data_dir=tmp_path / ".data")
    assert lp.skills == ("flag-risk", "estimate-effort")


def test_profile_no_skills_block_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    from src.profile.loader import load_profile

    base = _write_profile(tmp_path, "acme", "name: Acme\n")
    lp = load_profile("acme", profiles_dir=base, data_dir=tmp_path / ".data")
    assert lp.skills == ()


def test_default_profile_has_no_skills(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    from src.profile.loader import load_profile
    from src.runtime.agent_paths import agent_data_dir

    lp = load_profile("default", data_dir=agent_data_dir("default"))
    assert lp.skills == ()  # default profile ships with no skills block — unchanged behavior
