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
    INHERITED_GAP_RULE,
    NONPUBLIC_RULE,
    REQUEST_CEILING_RULE,
    SOURCE_LABEL_RULE,
    SOURCE_RULE,
)
from my_crew.llm.team_task_check_prompt import _CHECK_SYSTEM
from my_crew.llm.team_task_prompt import _REVIEW_SYSTEM

RULES = (SOURCE_RULE, COUNTABLE_RULE, SOURCE_LABEL_RULE, REQUEST_CEILING_RULE,
         NONPUBLIC_RULE)


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


def test_both_graders_carry_the_inherited_gap_rule():
    """A step downstream of a skipped one receives a 'KHÔNG CÓ KẾT QUẢ' handoff. The
    worker side already has the honesty rule (name the gap, don't fabricate); without
    the symmetric grading rule, both graders would fail the honest result for the very
    gap it honestly named — turning every skip into a review-death one step later.
    Byte-identical from the one constant — the rule lived as two verbatim copies in
    the two prompt modules, the exact drift shape this module exists to prevent."""
    assert INHERITED_GAP_RULE in _CHECK_SYSTEM
    assert INHERITED_GAP_RULE in _REVIEW_SYSTEM


def test_every_layer_honors_a_salvaged_draft():
    """A drop can carry the dead step's last failed draft (8/10 measured drops had
    one). The draft only helps if EVERY layer agrees labeled use of it is legitimate:
    the placeholder must invite use under the label, the worker honesty rule must
    carve the exception, both graders (via the shared gap rule) must not call it
    fabrication, the rework prompt must not claim 'no source exists', and the source
    rule's placeholder⇒fabricated sentence must exempt draft-traceable figures. One
    dissenting layer re-creates the starved-downstream death the salvage fixes."""
    from my_crew.agent.ops_stalled_task import (
        _DROPPED_WITH_DRAFT_TEXT,
        SALVAGE_DRAFT_PREFIX,
    )
    from my_crew.llm.team_task_check_prompt import _REWORK_SYSTEM
    from my_crew.llm.team_task_prompt import _SYSTEM

    marker = "BẢN NHÁP CHƯA ĐẠT SOÁT"
    assert SALVAGE_DRAFT_PREFIX.startswith(marker)
    label = "dữ liệu chưa qua soát"
    for text in (_DROPPED_WITH_DRAFT_TEXT + SALVAGE_DRAFT_PREFIX, INHERITED_GAP_RULE,
                 _SYSTEM, _REWORK_SYSTEM, SOURCE_RULE):
        assert marker in text
    for text in (_DROPPED_WITH_DRAFT_TEXT, INHERITED_GAP_RULE, _SYSTEM,
                 _REWORK_SYSTEM):
        assert label in text


def test_every_layer_accepts_an_honest_nonpublic_cell():
    """A grid brief whose data is partly unpublished ('liên hệ bán hàng' pricing) can
    only complete if EVERY layer that touches the result agrees an honestly marked
    'không công khai (đã tra: nguồn)' cell is finished work: the worker must write it,
    both graders must pass it, the stuck judge must not give the step up over it, and
    the decompose planner must leave the escape hatch in the criteria. One dissenting
    layer re-creates the measured 0/6 grid-brief death."""
    from my_crew.llm.stuck_judgement_prompt import STUCK_JUDGE_SYSTEM
    from my_crew.llm.team_task_prompt import _DECOMPOSE_SYSTEM, _SYSTEM

    assert "QUY TẮC DỮ LIỆU KHÔNG CÔNG KHAI" in NONPUBLIC_RULE
    assert "QUY TẮC Ô KHÔNG CÔNG KHAI" in _SYSTEM
    assert "QUY TẮC DỮ LIỆU KHÔNG CÔNG KHAI" in STUCK_JUDGE_SYSTEM
    assert "kèm nguồn đã tra là ĐẠT ô đó" in _DECOMPOSE_SYSTEM


def test_the_ceiling_rule_scopes_the_grade_to_the_step_not_the_whole_brief():
    """Measured live: a step whose criteria covered only part (1a) of a three-part brief
    was failed for not delivering (1b) and (2) — the sibling steps' work. The rule must
    say a step is ONE part and the untouched parts belong to other steps."""
    assert "MỘT phần" in REQUEST_CEILING_RULE
    assert "việc của bước khác" in REQUEST_CEILING_RULE
