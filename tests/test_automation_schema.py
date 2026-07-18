"""M3-P12 S3 (D3): automation.yaml schema parser — strict, fail-closed validation."""

from __future__ import annotations

import pytest

from my_crew.automation.schema import (
    AnalyzeStep,
    ProposeStep,
    ReadStep,
    parse_automation,
)


def _doc(**over):
    base = {
        "name": "wf",
        "steps": [
            {"read": "jira.issues", "args": {}, "as": "issues"},
            {"analyze": "summarize_blockers", "using": ["issues"], "as": "note"},
            {"propose": "slack.post", "args": {"channel": "c", "text": "{{note}}"}},
        ],
    }
    base.update(over)
    return base


def test_valid_workflow_parses():
    wf = parse_automation(_doc())
    assert wf.name == "wf"
    assert [type(s).__name__ for s in wf.steps] == ["ReadStep", "AnalyzeStep", "ProposeStep"]
    assert isinstance(wf.steps[0], ReadStep)
    assert isinstance(wf.steps[1], AnalyzeStep)
    assert isinstance(wf.steps[2], ProposeStep)


def test_unknown_read_tool_rejected():
    with pytest.raises(ValueError, match="unknown read tool"):
        parse_automation(_doc(steps=[{"read": "evil.exec", "as": "x"}]))


def test_unknown_propose_target_rejected():
    with pytest.raises(ValueError, match="unknown propose target"):
        parse_automation(_doc(steps=[{"propose": "gh.delete", "args": {}}]))


def test_unknown_analyze_prompt_rejected():
    with pytest.raises(ValueError, match="unknown analyze prompt"):
        parse_automation(_doc(steps=[{"analyze": "free_text_inject", "as": "x"}]))


def test_unknown_step_type_rejected():
    with pytest.raises(ValueError, match="no known type"):
        parse_automation(_doc(steps=[{"frobnicate": "x"}]))


def test_missing_name_rejected():
    with pytest.raises(ValueError, match="name"):
        parse_automation({"steps": [{"read": "jira.issues", "as": "x"}]})


def test_empty_steps_rejected():
    with pytest.raises(ValueError, match="steps"):
        parse_automation({"name": "wf", "steps": []})


# --- when condition: single `field == value` only ---


def test_when_single_comparison_parses():
    wf = parse_automation(_doc(when="priority == P0"))
    assert wf.when.field == "priority" and wf.when.value == "P0"


def test_when_strips_quotes():
    wf = parse_automation(_doc(when="status == 'overdue'"))
    assert wf.when.value == "overdue"


@pytest.mark.parametrize(
    "bad",
    [
        "a == b and c == d",  # boolean operator
        "a == b or c == d",
        "a != b",  # non-== operator
        "a >= b",
        "status overdue",  # no ==
        "== value",  # empty field
        "field ==",  # empty value
    ],
)
def test_when_compound_or_malformed_rejected(bad):
    with pytest.raises(ValueError):
        parse_automation(_doc(when=bad))
