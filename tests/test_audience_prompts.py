"""Slice A: audience-aware prompts (internal byte-identical, external leak-free)."""

from __future__ import annotations

import pytest

from src.llm import okr_report_prompt, report_prompt, resource_report_prompt
from src.tools.models import (
    AssigneeLoad,
    CostSummary,
    KeyResult,
    Objective,
    ResourceReport,
    Risk,
)

D = "2026-06-22"
RISKS = [
    Risk("overdue_task", "high", "SCRUM-15", "PR #42 treo", "ping assignee", ("SCRUM-15",)),
    Risk("blocker", "medium", "SCRUM-7", "bị chặn", "gỡ blocker", ("SCRUM-7",)),
]


# --- backward-compat: internal == default == current behavior (byte-identical) ---


def test_report_messages_internal_unchanged():
    default = report_prompt.build_report_messages(RISKS, report_date=D)
    explicit = report_prompt.build_report_messages(RISKS, report_date=D, audience="internal")
    assert default == explicit
    assert default[0]["content"] == report_prompt._SYSTEM  # unchanged system prompt
    assert "SCRUM-15" in default[1]["content"]  # internal carries the key


def test_detail_messages_internal_unchanged():
    default = report_prompt.build_detail_messages(RISKS, report_date=D, kind="weekly")
    explicit = report_prompt.build_detail_messages(
        RISKS, report_date=D, kind="weekly", audience="internal"
    )
    assert default == explicit
    assert default[0]["content"] == report_prompt._DETAIL_SYSTEM


def test_slack_short_internal_unchanged():
    default = report_prompt.build_slack_short(RISKS, report_date=D, detail_url="u")
    explicit = report_prompt.build_slack_short(
        RISKS, report_date=D, detail_url="u", audience="internal"
    )
    assert default == explicit
    assert "Nổi bật: SCRUM-15" in default  # internal keeps the headline


# --- external: business tone, no internal detail leaks ---


def test_report_messages_external_no_keys():
    msgs = report_prompt.build_report_messages(RISKS, report_date=D, audience="external")
    blob = msgs[0]["content"] + msgs[1]["content"]
    assert "SCRUM-15" not in blob and "SCRUM-7" not in blob and "#42" not in blob
    assert "stakeholder" in blob.lower()


def test_detail_messages_external_no_keys():
    msgs = report_prompt.build_detail_messages(
        RISKS, report_date=D, kind="weekly", audience="external"
    )
    blob = msgs[0]["content"] + msgs[1]["content"]
    assert "SCRUM-15" not in blob and "#42" not in blob


def test_slack_short_external_drops_headline():
    out = report_prompt.build_slack_short(RISKS, report_date=D, detail_url="u", audience="external")
    assert "SCRUM-15" not in out and "Nổi bật" not in out
    assert "2 rủi ro" in out  # counts still shown


def test_summarize_risks_has_no_keys():
    summary = report_prompt._summarize_risks(RISKS)
    assert "SCRUM-15" not in summary and "#42" not in summary
    assert "2" in summary  # count


# --- OKR audience ---


def _rollup():
    obj = Objective("Tăng retention", (KeyResult("KR1", ("E-1",), None, 40.0),), 40.0)
    return okr_report_prompt.OkrRollup(objectives=(obj,), problems=(), at_risk=("Tăng retention",))


def test_okr_narrative_internal_unchanged():
    default = okr_report_prompt.build_okr_narrative_messages(_rollup(), report_date=D)
    explicit = okr_report_prompt.build_okr_narrative_messages(
        _rollup(), report_date=D, audience="internal"
    )
    assert default == explicit


def test_okr_narrative_external_business_tone():
    msgs = okr_report_prompt.build_okr_narrative_messages(
        _rollup(), report_date=D, audience="external"
    )
    assert "STAKEHOLDER" in msgs[0]["content"]
    # objective names are business-level → may appear
    assert "Tăng retention" in msgs[1]["content"]


def test_okr_slack_short_external_drops_problems_line():
    from src.tools.models import OkrProblem

    rollup = okr_report_prompt.OkrRollup(
        objectives=_rollup().objectives, problems=(OkrProblem("r", "bad"),), at_risk=()
    )
    internal = okr_report_prompt.build_okr_slack_short(rollup, report_date=D, detail_url="u")
    external = okr_report_prompt.build_okr_slack_short(
        rollup, report_date=D, detail_url="u", audience="external"
    )
    assert "có vấn đề" in internal
    assert "có vấn đề" not in external  # internal data-quality noise dropped


# --- Resource audience (privacy: no names / labor for external) ---


def _resource():
    return ResourceReport(
        loads=(AssigneeLoad("Alice", 6, 2, 1, overloaded=True),),
        team_mean=3.0, overloaded=("Alice",), unassigned_count=2,
    )


def _cost():
    return CostSummary(45.0, 50.0, 0.9, "warn", 200.0, 8, 25.0)


def test_resource_narrative_internal_unchanged():
    default = resource_report_prompt.build_resource_narrative_messages(
        _resource(), _cost(), report_date=D
    )
    explicit = resource_report_prompt.build_resource_narrative_messages(
        _resource(), _cost(), report_date=D, audience="internal"
    )
    assert default == explicit


def test_resource_external_short_no_names_no_labor():
    out = resource_report_prompt.build_resource_slack_short(
        _resource(), _cost(), report_date=D, detail_url="u", audience="external"
    )
    assert "Alice" not in out  # no assignee name
    assert "$200" not in out and "Nhân công" not in out  # no labor cost
    assert "6 issue" not in out and "người" not in out  # no per-person/headcount detail
    assert "căng tải" in out  # capacity word present (Alice is overloaded)


def test_resource_external_narrative_no_names():
    msgs = resource_report_prompt.build_resource_narrative_messages(
        _resource(), _cost(), report_date=D, audience="external"
    )
    blob = msgs[0]["content"] + msgs[1]["content"]
    assert "Alice" not in blob
    assert "căng tải" in blob


def test_resource_external_fallback_no_names():
    out = resource_report_prompt.fallback_resource_narrative(
        _resource(), _cost(), report_date=D, audience="external"
    )
    assert "Alice" not in out and out.startswith("<p>")


# --- config validation (the guardrail foot-gun) ---


def _build_config(*, stakeholder, external):
    """Build reporting config from a pure dict (no env, no cache) to exercise the
    stakeholder-channel cross-validation guardrail."""
    from src.config.config_builders import build_reporting_config_from_dict

    return build_reporting_config_from_dict(
        {"slack_stakeholder_channel": stakeholder, "slack_external_channels": external}
    )


def test_stakeholder_channel_in_external_set_ok():
    cfg = _build_config(stakeholder="C_EXT", external="C_EXT,C_OTHER")
    assert cfg.slack_stakeholder_channel == "C_EXT"


def test_stakeholder_channel_not_in_external_raises():
    with pytest.raises(RuntimeError, match="SLACK_EXTERNAL_CHANNELS"):
        _build_config(stakeholder="C_EXT", external="C_OTHER")


def test_stakeholder_channel_unset_is_none():
    cfg = _build_config(stakeholder="", external="")
    assert cfg.slack_stakeholder_channel is None
