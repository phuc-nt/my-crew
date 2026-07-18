"""M3-P10 Slice 2: skill selector + render + select_skill_text (offline)."""

from __future__ import annotations

from my_crew.profile.context import ProfileContext
from my_crew.skills.models import Skill
from my_crew.skills.skill_selector import (
    make_llm_selector,
    render_skills,
    select_skill_text,
)

_S1 = Skill("flag-risk", "phát hiện rủi ro", "BODY-FLAG", ("daily", "weekly"))
_S2 = Skill("estimate-effort", "ước lượng", "BODY-EST", ("weekly",))
_POOL = (_S1, _S2)


# --- render_skills ---


def test_render_skills_wraps_bodies():
    out = render_skills([_S1, _S2])
    assert out.startswith("<pm_skills>\n") and out.endswith("\n</pm_skills>")
    assert "BODY-FLAG" in out and "BODY-EST" in out


def test_render_skills_empty_is_blank():
    assert render_skills([]) == ""


# --- select_skill_text: the internal/external gate + pool filter ---


def _ctx(skills, selector):
    return ProfileContext(skills=skills, skill_selector=selector)


def test_select_external_is_blank():
    # The RED LINE: external audience never runs the selector, never injects skills.
    ran = []
    ctx = _ctx(_POOL, lambda pool, kind: (ran.append(1), ["flag-risk"])[1])
    assert select_skill_text(ctx, "external", kind="daily") == ""
    assert ran == []  # selector not even invoked on the external path


def test_select_internal_injects_chosen():
    ctx = _ctx(_POOL, lambda pool, kind: ["flag-risk"])
    out = select_skill_text(ctx, "internal", kind="daily")
    assert "BODY-FLAG" in out and "BODY-EST" not in out  # only the chosen one


def test_select_filters_unknown_names():
    # A hallucinated / out-of-pool name is dropped (only pool members render).
    ctx = _ctx(_POOL, lambda pool, kind: ["flag-risk", "not-a-real-skill"])
    out = select_skill_text(ctx, "internal", kind="daily")
    assert "BODY-FLAG" in out and "not-a-real-skill" not in out


def test_select_no_candidates_is_blank():
    ctx = _ctx((), lambda pool, kind: ["flag-risk"])
    assert select_skill_text(ctx, "internal", kind="daily") == ""


def test_select_no_selector_is_blank():
    ctx = _ctx(_POOL, None)
    assert select_skill_text(ctx, "internal", kind="daily") == ""


def test_select_none_chosen_is_blank():
    ctx = _ctx(_POOL, lambda pool, kind: [])
    assert select_skill_text(ctx, "internal", kind="daily") == ""


# --- make_llm_selector: parses names, tolerates failure ---


class _FakeLlm:
    def __init__(self, reply):
        self._reply = reply

    def complete(self, messages):
        class _R:
            content = self._reply

        return _R()


def test_llm_selector_parses_names():
    sel = make_llm_selector(_FakeLlm("flag-risk\nestimate-effort"))
    assert set(sel(list(_POOL), "weekly")) == {"flag-risk", "estimate-effort"}


def test_llm_selector_strips_bullets_and_commas():
    sel = make_llm_selector(_FakeLlm("- flag-risk, estimate-effort"))
    assert set(sel(list(_POOL), "weekly")) == {"flag-risk", "estimate-effort"}


def test_llm_selector_empty_pool_skips_call():
    called = []

    class _Spy:
        def complete(self, messages):
            called.append(1)
            raise AssertionError("should not be called for empty pool")

    sel = make_llm_selector(_Spy())
    assert sel([], "weekly") == []
    assert called == []


def test_llm_selector_tolerates_failure():
    class _Boom:
        def complete(self, messages):
            raise RuntimeError("no key")

    sel = make_llm_selector(_Boom())
    assert sel(list(_POOL), "weekly") == []  # failure → no skills, never raises
