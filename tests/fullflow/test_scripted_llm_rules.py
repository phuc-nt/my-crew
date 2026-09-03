"""The scripted LLM double must key work rules on the step's OWN title.

Scenarios script one `step_work` rule per plan step, in plan order; the double
picks the first rule whose marker appears in the prompt. The worker prompt also
lists the other steps' titles as a scope boundary, so the matcher has to look
past that block or the first step's rule answers every later step.
"""

from __future__ import annotations


def test_a_work_rule_does_not_fire_on_a_sibling_title_in_the_scope_block():
    """The worker prompt lists the other steps' titles as a boundary. Rule order in
    a scenario follows plan order, so without this the FIRST step's rule would
    answer every later step whose brief names it."""
    from my_crew.agent.step_delegation_brief import delegation_brief
    from tests.fullflow import scenario_rules as rules
    from tests.fullflow.scripted_llm import ScriptedLlm

    llm = ScriptedLlm(
        [rules.step_work("Soạn nháp", "NHÁP"), rules.step_work("Chốt bài", "CHỐT")],
        trace=lambda *a, **k: None,
    )
    prompt = "Đầu việc: Chốt bài\n\n" + delegation_brief("đủ 3 mục", ["Soạn nháp"]) + "\n\nLàm đi."
    out = llm.complete([{"role": "user", "content": prompt}], role="content")

    assert out.content == "CHỐT"
