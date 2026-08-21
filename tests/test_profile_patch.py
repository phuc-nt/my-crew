"""v87 P2: ruamel round-trip profile.yaml patcher — the one sanctioned web-write path.

Load-bearing:
- Comment preservation: patching `safety.dry_run` must not disturb any other comment,
  hand-written key (incl. unicode), or key order in the document (the save_company
  rebuild-from-dict lesson).
- Nested-key creation when the `safety:` block is entirely absent.
- Only whitelisted block/leaf combos are writable; everything else 400s before any
  file is touched.
- Unknown agent id -> a clear, typed error (ProfileNotFoundError), not a raw OSError.
"""

from __future__ import annotations

import pytest

from my_crew.server import profile_patch


@pytest.fixture
def profiles_home(tmp_path, monkeypatch):
    """A throwaway `profiles/<id>/profile.yaml` tree; MY_CREW_HOME repointed at it."""
    monkeypatch.setattr(profile_patch, "MY_CREW_HOME", tmp_path)
    return tmp_path


def _write_profile(home, agent_id: str, text: str):
    d = home / "profiles" / agent_id
    d.mkdir(parents=True)
    (d / "profile.yaml").write_text(text, encoding="utf-8")
    return d / "profile.yaml"


def test_patch_preserves_comments_and_unknown_keys(profiles_home):
    path = _write_profile(
        profiles_home,
        "acme",
        "# fleet identity — do not remove\n"
        "name: acme\n"
        "domain: pm\n"
        "weird_handwritten_key: xin chào thế giới\n"  # unicode + a key the loader doesn't model
        "safety:\n"
        "  trust_mode: autonomous  # CEO set this by hand\n"
        "  dry_run: true\n"
        "budget:\n"
        "  monthly_usd: 50\n",
    )
    before = path.read_text(encoding="utf-8")

    profile_patch.patch_profile_yaml("acme", {"safety": {"dry_run": False}})

    after = path.read_text(encoding="utf-8")
    # Every line except the dry_run value is byte-identical.
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    assert len(before_lines) == len(after_lines)
    diff = [
        (b, a) for b, a in zip(before_lines, after_lines, strict=True) if b != a
    ]
    assert diff == [("  dry_run: true", "  dry_run: false")]
    # Comments, unicode key, and unrelated blocks survive verbatim.
    assert "# fleet identity — do not remove" in after
    assert "weird_handwritten_key: xin chào thế giới" in after
    assert "# CEO set this by hand" in after
    assert "monthly_usd: 50" in after
    assert "dry_run: false" in after
    assert "dry_run: true" not in after


def test_patch_creates_safety_block_when_absent(profiles_home):
    path = _write_profile(profiles_home, "bare", "name: bare\ndomain: pm\n")

    profile_patch.patch_profile_yaml("bare", {"safety": {"dry_run": False}})

    after = path.read_text(encoding="utf-8")
    assert "name: bare" in after
    assert "safety:" in after
    assert "dry_run: false" in after


def test_patch_creates_safety_block_when_null(profiles_home):
    """`safety:` present but empty (null) must not crash the merge — same as absent."""
    _write_profile(profiles_home, "nully", "name: nully\ndomain: pm\nsafety:\n")

    profile_patch.patch_profile_yaml("nully", {"safety": {"dry_run": True}})

    assert profile_patch.read_safety_dry_run_raw("nully") is True


def test_patch_rejects_unknown_block(profiles_home):
    _write_profile(profiles_home, "acme", "name: acme\ndomain: pm\n")
    with pytest.raises(profile_patch.DisallowedPatchKeyError):
        profile_patch.patch_profile_yaml("acme", {"bindings": {"jira": {"project_key": "X"}}})


def test_patch_rejects_unknown_leaf_under_allowed_block(profiles_home):
    _write_profile(profiles_home, "acme", "name: acme\ndomain: pm\nsafety:\n  dry_run: true\n")
    with pytest.raises(profile_patch.DisallowedPatchKeyError):
        profile_patch.patch_profile_yaml("acme", {"safety": {"write_disabled": True}})
    # Rejected patch must not touch the file.
    assert profile_patch.read_safety_dry_run_raw("acme") is True


def test_patch_unknown_agent_raises_clear_error(profiles_home):
    with pytest.raises(profile_patch.ProfileNotFoundError):
        profile_patch.patch_profile_yaml("no-such-agent", {"safety": {"dry_run": True}})


def test_patch_invalid_agent_id_raises_profile_not_found(profiles_home):
    """A path-escape-ish id must fail as ProfileNotFoundError (validated before any I/O),
    not leak a raw ValueError or, worse, resolve outside profiles/."""
    with pytest.raises(profile_patch.ProfileNotFoundError):
        profile_patch.patch_profile_yaml("../../etc", {"safety": {"dry_run": True}})


def test_read_safety_dry_run_raw_absent_returns_none(profiles_home):
    _write_profile(profiles_home, "acme", "name: acme\ndomain: pm\n")
    assert profile_patch.read_safety_dry_run_raw("acme") is None


def test_patch_idempotent_same_value_noop_content(profiles_home):
    path = _write_profile(
        profiles_home, "acme", "name: acme\ndomain: pm\nsafety:\n  dry_run: true\n"
    )
    profile_patch.patch_profile_yaml("acme", {"safety": {"dry_run": True}})
    text1 = path.read_text(encoding="utf-8")
    profile_patch.patch_profile_yaml("acme", {"safety": {"dry_run": True}})
    text2 = path.read_text(encoding="utf-8")
    assert text1 == text2
