"""The step system prompt must forbid a chain-of-thought preamble.

Native team tasks never needed this rule: every step's text was rewritten by the
aggregate summarizer before delivery, and THAT prompt has carried an explicit
"start with the summary, no reasoning" rule since the day qwen3.7-plus was observed
prepending an English preamble. Sprint mode changed the economics — a sprint task's
single artifact IS the deliverable, so `make_aggregate` returns it verbatim and the
summarizer never runs. UAT task 2cab14de8458 delivered ~2000 characters of "The user
wants me to..." / "Wait, the prompt says..." to the CEO ahead of a correct report.

The preamble carries no delimiter and even contains a rough draft of the real answer,
so there is no safe text-boundary strip and the model exposes no separate reasoning
field to drop — the prompt rule is the fix, which makes it worth pinning.
"""

from __future__ import annotations

from my_crew.llm.team_task_prompt import _SYSTEM, build_team_step_messages


def test_the_step_prompt_forbids_a_reasoning_preamble():
    assert "KHÔNG viết quá trình suy nghĩ" in _SYSTEM
    assert "bắt đầu" in _SYSTEM and "NGAY" in _SYSTEM


def test_the_step_prompt_still_forbids_inventing_missing_data():
    """The format rule was appended next to the honesty rule; neither may displace
    the other, since a sprint step that meets the format and fabricates is worse
    than one that rambles."""
    assert "TUYỆT ĐỐI không được bịa" in _SYSTEM


def test_every_step_call_carries_both_rules_in_its_system_message():
    messages = build_team_step_messages(step_title="soạn báo cáo")

    assert messages[0]["role"] == "system"
    system = messages[0]["content"]
    assert "KHÔNG viết quá trình suy nghĩ" in system
    assert "TUYỆT ĐỐI không được bịa" in system
