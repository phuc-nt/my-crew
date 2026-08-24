"""Both graders of a step's result must apply the same evidence bar.

A step is graded twice against the same acceptance criteria — the worker's own
`self_check` and a colleague's peer `review`. They are two readers, not two standards.
The rules lived as separate copies in the two prompt modules and drifted: peer review
lost the countable-requirement rule and the original-ask ceiling, so it passed results
that self-check would have failed. These tests fail if the copies ever come back.
"""

from my_crew.llm.grading_rules import (
    COUNTABLE_RULE,
    EVIDENCE_RULES,
    REQUEST_CEILING_RULE,
    SOURCE_LABEL_RULE,
    SOURCE_RULE,
)
from my_crew.llm.team_task_check_prompt import _CHECK_SYSTEM
from my_crew.llm.team_task_prompt import _REVIEW_SYSTEM

RULES = (SOURCE_RULE, COUNTABLE_RULE, SOURCE_LABEL_RULE, REQUEST_CEILING_RULE)


def test_both_graders_carry_every_evidence_rule():
    for rule in RULES:
        head = rule.split(":")[0]
        assert rule in _CHECK_SYSTEM, f"self-check lost {head}"
        assert rule in _REVIEW_SYSTEM, f"peer review lost {head}"


def test_the_rules_are_the_same_text_in_both_prompts():
    """Not merely 'both mention sources' — byte-identical, from the one constant.
    Paraphrased copies are how the two graders drifted in the first place."""
    assert EVIDENCE_RULES in _CHECK_SYSTEM
    assert EVIDENCE_RULES in _REVIEW_SYSTEM


def test_provenance_is_judged_before_the_criteria():
    """A fabricated figure satisfies a rubric it was invented to satisfy, so the source
    rule only works if the grader applies it first. Order in the prompt is the only
    thing making that true."""
    for prompt in (_CHECK_SYSTEM, _REVIEW_SYSTEM):
        assert prompt.index(SOURCE_RULE) < prompt.index(COUNTABLE_RULE)


def test_each_grader_keeps_the_contract_that_is_its_own():
    """Shared rules, separate output contracts — self-check reports a confidence,
    peer review reports notes and is denied any channel beyond the verdict."""
    assert "confidence" in _CHECK_SYSTEM and "confidence" not in _REVIEW_SYSTEM
    assert '"notes"' in _REVIEW_SYSTEM
    assert "đổi người phụ trách" in _REVIEW_SYSTEM
