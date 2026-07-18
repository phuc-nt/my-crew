"""M3-P9 A3 Slice 2: sibling-fact selector + internal-only injection (offline)."""

from __future__ import annotations

from my_crew.agent.sibling_selector import (
    make_llm_selector,
    render_sibling_facts,
    select_sibling_text,
)
from my_crew.llm import okr_report_prompt, report_prompt, resource_report_prompt
from my_crew.profile.context import ProfileContext
from my_crew.tools.models import (
    AssigneeLoad,
    CostSummary,
    KeyResult,
    Objective,
    ResourceReport,
    Risk,
)

_FACTS = ("A đã chốt deadline sprint 5 là 30/06", "A phụ thuộc API team backend")
_PICK_FIRST = lambda facts, kind: [facts[0]]  # noqa: E731 — tiny fake selector
D = "2026-06-26"
RISKS = [Risk("blocker", "high", "SCRUM-1", "kẹt", "gỡ", ("SCRUM-1",))]
SIB_MARKER = "X-SIBLING-MARKER"

_OKR = okr_report_prompt.OkrRollup(
    objectives=(Objective("Obj", (KeyResult("KR", ("E-1",), None, 40.0),), 40.0),),
    problems=(),
    at_risk=(),
)
_RES = ResourceReport((AssigneeLoad("Alice", 6, 0, 0, overloaded=True),), 6.0, ("Alice",), 0)
_COST = CostSummary(0.0, 50.0, 0.0, "ok", 0.0, 6, 0.0)


def _ctx(facts=_FACTS, selector=_PICK_FIRST, project="acme"):
    return ProfileContext(sibling_facts=facts, sibling_selector=selector, sibling_project=project)


# --- render ---


def test_render_sibling_facts_labeled_block():
    out = render_sibling_facts(["fact one", "fact two"], "acme")
    assert "--- Bộ nhớ agent khác (project: acme) ---" in out
    assert "fact one" in out and "fact two" in out


def test_render_empty_is_empty_string():
    assert render_sibling_facts([], "acme") == ""


# --- select_sibling_text: the internal/external gate ---


def test_select_internal_returns_block():
    out = select_sibling_text(_ctx(), "internal", kind="daily", project_group="acme")
    assert "project: acme" in out
    assert _FACTS[0] in out and _FACTS[1] not in out  # only the picked one


def test_select_external_returns_empty():
    # RED LINE: external never runs the selector / never injects.
    ran = []
    ctx = _ctx(selector=lambda f, k: (ran.append(1), [f[0]])[1])
    assert select_sibling_text(ctx, "external", kind="daily", project_group="acme") == ""
    assert ran == []


def test_select_no_facts_or_no_selector_empty():
    assert select_sibling_text(_ctx(facts=()), "internal", kind="daily", project_group="acme") == ""
    assert select_sibling_text(
        _ctx(selector=None), "internal", kind="daily", project_group="acme"
    ) == ""


# --- make_llm_selector: parse, graceful failure, hallucination guard ---


class _FakeLlm:
    def __init__(self, reply):
        self._reply = reply

    def complete(self, messages):
        class _R:
            content = self._reply

        return _R()


def test_make_llm_selector_keeps_input_facts():
    sel = make_llm_selector(_FakeLlm(f"{_FACTS[0]}\n{_FACTS[1]}"))
    assert sel(list(_FACTS), "weekly") == list(_FACTS)


def test_selector_drops_hallucinated_facts():
    # The LLM returns a fact NOT in the input ⇒ filtered out (only input facts survive).
    sel = make_llm_selector(_FakeLlm(f"{_FACTS[0]}\nBỊA: một fact không có trong input"))
    assert sel(list(_FACTS), "weekly") == [_FACTS[0]]


def test_make_llm_selector_graceful_on_failure():
    class _Boom:
        def complete(self, messages):
            raise RuntimeError("no key")

    sel = make_llm_selector(_Boom())
    assert sel(list(_FACTS), "weekly") == []  # failure → drop all, never raises
    # and the gate then yields "":
    ctx = ProfileContext(sibling_facts=_FACTS, sibling_selector=sel, sibling_project="acme")
    assert select_sibling_text(ctx, "internal", kind="weekly", project_group="acme") == ""


# --- RED LINE per builder: internal injects, external byte-identical (no marker) ---


def _blob(messages):
    return "".join(m["content"] for m in messages)


def test_report_internal_injects_external_ignores():
    internal = report_prompt.build_report_messages(RISKS, report_date=D, sibling_facts=SIB_MARKER)
    ext_with = report_prompt.build_report_messages(
        RISKS, report_date=D, audience="external", sibling_facts=SIB_MARKER
    )
    ext_without = report_prompt.build_report_messages(RISKS, report_date=D, audience="external")
    assert SIB_MARKER in _blob(internal)
    assert SIB_MARKER not in _blob(ext_with)
    assert ext_with == ext_without  # external byte-identical with/without sibling facts


def test_detail_internal_injects_external_ignores():
    internal = report_prompt.build_detail_messages(
        RISKS, report_date=D, kind="daily", sibling_facts=SIB_MARKER
    )
    ext_with = report_prompt.build_detail_messages(
        RISKS, report_date=D, kind="daily", audience="external", sibling_facts=SIB_MARKER
    )
    ext_without = report_prompt.build_detail_messages(
        RISKS, report_date=D, kind="daily", audience="external"
    )
    assert SIB_MARKER in _blob(internal)
    assert SIB_MARKER not in _blob(ext_with) and ext_with == ext_without


def test_okr_internal_injects_external_ignores():
    internal = okr_report_prompt.build_okr_narrative_messages(
        _OKR, report_date=D, sibling_facts=SIB_MARKER
    )
    ext_with = okr_report_prompt.build_okr_narrative_messages(
        _OKR, report_date=D, audience="external", sibling_facts=SIB_MARKER
    )
    ext_without = okr_report_prompt.build_okr_narrative_messages(
        _OKR, report_date=D, audience="external"
    )
    assert SIB_MARKER in _blob(internal)
    assert SIB_MARKER not in _blob(ext_with) and ext_with == ext_without


def test_resource_internal_injects_external_ignores():
    internal = resource_report_prompt.build_resource_narrative_messages(
        _RES, _COST, report_date=D, sibling_facts=SIB_MARKER
    )
    ext_with = resource_report_prompt.build_resource_narrative_messages(
        _RES, _COST, report_date=D, audience="external", sibling_facts=SIB_MARKER
    )
    ext_without = resource_report_prompt.build_resource_narrative_messages(
        _RES, _COST, report_date=D, audience="external"
    )
    assert SIB_MARKER in _blob(internal)
    assert SIB_MARKER not in _blob(ext_with) and ext_with == ext_without


# --- backward-compat: sibling_facts="" byte-identical to no-arg per builder ---


def test_empty_sibling_facts_byte_identical():
    assert report_prompt.build_report_messages(
        RISKS, report_date=D
    ) == report_prompt.build_report_messages(RISKS, report_date=D, sibling_facts="")
    assert report_prompt.build_detail_messages(
        RISKS, report_date=D, kind="weekly"
    ) == report_prompt.build_detail_messages(RISKS, report_date=D, kind="weekly", sibling_facts="")
    assert okr_report_prompt.build_okr_narrative_messages(
        _OKR, report_date=D
    ) == okr_report_prompt.build_okr_narrative_messages(_OKR, report_date=D, sibling_facts="")
    assert resource_report_prompt.build_resource_narrative_messages(
        _RES, _COST, report_date=D
    ) == resource_report_prompt.build_resource_narrative_messages(
        _RES, _COST, report_date=D, sibling_facts=""
    )
