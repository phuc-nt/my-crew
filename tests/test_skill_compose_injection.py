"""M3-P10 Slice 2: skill text injection into the 3 compose builders.

Each builder must: inject the `<pm_skills>` body into the INTERNAL prompt, take
NOTHING from skills on the EXTERNAL path (the P5 red line), and be byte-identical
to the no-skills call when `skills=""` (backward compat).
"""

from __future__ import annotations

from my_crew.llm import okr_report_prompt, report_prompt, resource_report_prompt
from my_crew.tools.models import (
    AssigneeLoad,
    CostSummary,
    KeyResult,
    Objective,
    ResourceReport,
    Risk,
)

D = "2026-06-22"
RISKS = [Risk("blocker", "high", "SCRUM-1", "kẹt", "gỡ", ("SCRUM-1",))]
SKILL = "<pm_skills>\nHƯỚNG DẪN KỸ NĂNG ĐẶC BIỆT\n</pm_skills>"

_OKR = okr_report_prompt.OkrRollup(
    objectives=(Objective("Obj", (KeyResult("KR", ("E-1",), None, 40.0),), 40.0),),
    problems=(),
    at_risk=(),
)
_RES = ResourceReport((AssigneeLoad("Alice", 6, 0, 0, overloaded=True),), 6.0, ("Alice",), 0)
_COST = CostSummary(0.0, 50.0, 0.0, "ok", 0.0, 6, 0.0)


def _blob(messages):
    return messages[0]["content"] + messages[1]["content"]


# --- report (detail) builder ---


def test_detail_internal_injects_skill():
    msgs = report_prompt.build_detail_messages(RISKS, report_date=D, kind="daily", skills=SKILL)
    assert "HƯỚNG DẪN KỸ NĂNG ĐẶC BIỆT" in msgs[1]["content"]


def test_detail_external_ignores_skill():
    # RED LINE: skill text must never reach the external prompt.
    msgs = report_prompt.build_detail_messages(
        RISKS, report_date=D, kind="daily", audience="external", skills=SKILL
    )
    assert "HƯỚNG DẪN KỸ NĂNG ĐẶC BIỆT" not in _blob(msgs)
    assert "pm_skills" not in _blob(msgs)


def test_detail_empty_skill_byte_identical():
    base = report_prompt.build_detail_messages(RISKS, report_date=D, kind="daily")
    with_empty = report_prompt.build_detail_messages(
        RISKS, report_date=D, kind="daily", skills=""
    )
    assert base == with_empty


def test_report_internal_injects_skill():
    msgs = report_prompt.build_report_messages(RISKS, report_date=D, skills=SKILL)
    assert "HƯỚNG DẪN KỸ NĂNG ĐẶC BIỆT" in msgs[1]["content"]


def test_report_external_ignores_skill():
    msgs = report_prompt.build_report_messages(
        RISKS, report_date=D, audience="external", skills=SKILL
    )
    assert "pm_skills" not in _blob(msgs)


def test_report_empty_skill_byte_identical():
    assert report_prompt.build_report_messages(
        RISKS, report_date=D
    ) == report_prompt.build_report_messages(RISKS, report_date=D, skills="")


# --- OKR narrative builder ---


def test_okr_internal_injects_skill():
    msgs = okr_report_prompt.build_okr_narrative_messages(_OKR, report_date=D, skills=SKILL)
    assert "HƯỚNG DẪN KỸ NĂNG ĐẶC BIỆT" in msgs[1]["content"]


def test_okr_external_ignores_skill():
    msgs = okr_report_prompt.build_okr_narrative_messages(
        _OKR, report_date=D, audience="external", skills=SKILL
    )
    assert "pm_skills" not in _blob(msgs)


def test_okr_empty_skill_byte_identical():
    assert okr_report_prompt.build_okr_narrative_messages(
        _OKR, report_date=D
    ) == okr_report_prompt.build_okr_narrative_messages(_OKR, report_date=D, skills="")


# --- resource narrative builder ---


def test_resource_internal_injects_skill():
    msgs = resource_report_prompt.build_resource_narrative_messages(
        _RES, _COST, report_date=D, skills=SKILL
    )
    assert "HƯỚNG DẪN KỸ NĂNG ĐẶC BIỆT" in msgs[1]["content"]


def test_resource_external_ignores_skill():
    msgs = resource_report_prompt.build_resource_narrative_messages(
        _RES, _COST, report_date=D, audience="external", skills=SKILL
    )
    assert "pm_skills" not in _blob(msgs)


def test_resource_empty_skill_byte_identical():
    assert resource_report_prompt.build_resource_narrative_messages(
        _RES, _COST, report_date=D
    ) == resource_report_prompt.build_resource_narrative_messages(
        _RES, _COST, report_date=D, skills=""
    )
