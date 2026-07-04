"""v7 M19 S2: company-doc injection into the 3 compose builders + the Q&A path.

THE RED LINE (mirrors test_skill_compose_injection): each builder injects the
`<company_docs>` block into the INTERNAL prompt, takes NOTHING from company docs on the
EXTERNAL path, and is byte-identical to the no-docs call when `company_docs=""`.
"""

from __future__ import annotations

from src.company_docs.inject import company_docs_text, render_company_docs
from src.company_docs.store import CompanyDoc
from src.llm import okr_report_prompt, report_prompt, resource_report_prompt
from src.profile.context import ProfileContext
from src.tools.models import (
    AssigneeLoad,
    CostSummary,
    KeyResult,
    Objective,
    ResourceReport,
    Risk,
)

D = "2026-06-22"
RISKS = [Risk("blocker", "high", "SCRUM-1", "kẹt", "gỡ", ("SCRUM-1",))]
SENTINEL = "NGHỈ PHÉP 12 NGÀY MỖI NĂM"
DOCS = f"<company_docs>\n## Chính sách\n{SENTINEL}\n</company_docs>"

_OKR = okr_report_prompt.OkrRollup(
    objectives=(Objective("Obj", (KeyResult("KR", ("E-1",), None, 40.0),), 40.0),),
    problems=(),
    at_risk=(),
)
_RES = ResourceReport((AssigneeLoad("Alice", 6, 0, 0, overloaded=True),), 6.0, ("Alice",), 0)
_COST = CostSummary(0.0, 50.0, 0.0, "ok", 0.0, 6, 0.0)


def _blob(messages):
    return messages[0]["content"] + messages[1]["content"]


# --- guard: company_docs_text obeys the audience red line ---


def test_company_docs_text_internal_renders():
    ctx = ProfileContext(company_docs=(CompanyDoc("p", "Chính sách", "", SENTINEL),))
    assert SENTINEL in company_docs_text(ctx, "internal")


def test_company_docs_text_external_is_empty():
    ctx = ProfileContext(company_docs=(CompanyDoc("p", "Chính sách", "", SENTINEL),))
    assert company_docs_text(ctx, "external") == ""


def test_company_docs_text_no_docs_is_empty():
    assert company_docs_text(ProfileContext(), "internal") == ""


# --- detail builder ---


def test_detail_internal_injects_docs():
    msgs = report_prompt.build_detail_messages(RISKS, report_date=D, kind="daily",
                                               company_docs=DOCS)
    assert SENTINEL in msgs[1]["content"]


def test_detail_external_ignores_docs():
    msgs = report_prompt.build_detail_messages(RISKS, report_date=D, kind="daily",
                                               audience="external", company_docs=DOCS)
    assert SENTINEL not in _blob(msgs)
    assert "company_docs" not in _blob(msgs)


def test_detail_empty_docs_byte_identical():
    base = report_prompt.build_detail_messages(RISKS, report_date=D, kind="daily")
    assert base == report_prompt.build_detail_messages(RISKS, report_date=D, kind="daily",
                                                       company_docs="")


# --- report (Slack) builder ---


def test_report_internal_injects_docs():
    msgs = report_prompt.build_report_messages(RISKS, report_date=D, company_docs=DOCS)
    assert SENTINEL in msgs[1]["content"]


def test_report_external_ignores_docs():
    msgs = report_prompt.build_report_messages(RISKS, report_date=D, audience="external",
                                               company_docs=DOCS)
    assert SENTINEL not in _blob(msgs)


def test_report_empty_docs_byte_identical():
    base = report_prompt.build_report_messages(RISKS, report_date=D)
    assert base == report_prompt.build_report_messages(RISKS, report_date=D, company_docs="")


# --- okr builder ---


def test_okr_internal_injects_docs():
    msgs = okr_report_prompt.build_okr_narrative_messages(_OKR, report_date=D, company_docs=DOCS)
    assert SENTINEL in msgs[1]["content"]


def test_okr_external_ignores_docs():
    msgs = okr_report_prompt.build_okr_narrative_messages(_OKR, report_date=D,
                                                          audience="external", company_docs=DOCS)
    assert SENTINEL not in _blob(msgs)


def test_okr_empty_docs_byte_identical():
    base = okr_report_prompt.build_okr_narrative_messages(_OKR, report_date=D)
    assert base == okr_report_prompt.build_okr_narrative_messages(_OKR, report_date=D,
                                                                 company_docs="")


# --- resource builder ---


def test_resource_internal_injects_docs():
    msgs = resource_report_prompt.build_resource_narrative_messages(
        _RES, _COST, report_date=D, company_docs=DOCS)
    assert SENTINEL in msgs[1]["content"]


def test_resource_external_ignores_docs():
    msgs = resource_report_prompt.build_resource_narrative_messages(
        _RES, _COST, report_date=D, audience="external", company_docs=DOCS)
    assert SENTINEL not in _blob(msgs)


def test_resource_empty_docs_byte_identical():
    base = resource_report_prompt.build_resource_narrative_messages(_RES, _COST, report_date=D)
    assert base == resource_report_prompt.build_resource_narrative_messages(
        _RES, _COST, report_date=D, company_docs="")


# --- render ordering: docs sit after skills, before siblings (internal) ---


def test_docs_render_between_skills_and_siblings():
    msgs = report_prompt.build_report_messages(
        RISKS, report_date=D, skills="<pm_skills>S</pm_skills>",
        company_docs=DOCS, sibling_facts="SIBLING")
    body = msgs[1]["content"]
    assert body.index("pm_skills") < body.index("company_docs") < body.index("SIBLING")


def test_render_company_docs_is_pure():
    # the render helper used by both the report builders and the Q&A path
    out = render_company_docs([CompanyDoc("p", "T", "", "BODY")])
    assert "<company_docs>" in out and "## T" in out and "BODY" in out
