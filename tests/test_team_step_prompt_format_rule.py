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


# --- the worker must know today's date, exactly like its graders do -------------------

def test_the_worker_is_told_todays_date_before_its_work_input():
    """The graders were date-anchored; the worker was not. A date-blind worker invents
    access dates from training priors (measured live: a step that searched on
    27/08/2026 stamped its citations "ngày truy cập 08/01/2025") and the date-anchored
    grader then fails the round over a date the producer could never have gotten right.
    """
    from datetime import datetime

    from my_crew.llm.team_task_prompt import worker_today_line

    messages = build_team_step_messages(
        step_title="tra cứu giá", handoff_context="dữ liệu bước trước"
    )

    user = messages[1]["content"]
    today = datetime.now().strftime("%d/%m/%Y")
    assert today in user
    # The anchor leads the step's own input: it must precede both the title line and
    # the prior-step handoff, so an over-long handoff cannot push it out of view.
    assert user.index(today) < user.index("Đầu việc:")
    assert user.index(today) < user.index("dữ liệu bước trước")
    # The worker line tells the producer what to DO with the date, not how to grade one.
    assert "KHÔNG tự suy ngày" in worker_today_line()


def test_both_graders_share_one_anchor_producer():
    """Review and self-check must carry the SAME anchor string — one producer, so the
    two grader prompts cannot drift apart the way the worker drifted from them."""
    from my_crew.llm.team_task_check_prompt import build_self_check_messages
    from my_crew.llm.team_task_prompt import grader_today_line

    check = build_self_check_messages(result_text="r", acceptance="- a")

    assert grader_today_line() in check[1]["content"]


def test_the_worker_is_told_which_artifact_it_owes():
    from my_crew.llm.team_task_prompt import build_team_step_messages

    msgs = build_team_step_messages(
        step_title="Tra cứu", artifact_contract="Bàn giao: bản THU THẬP cho bước sau dùng",
    )
    user = msgs[1]["content"]
    assert "Bàn giao: bản THU THẬP" in user
    assert user.index("Đầu việc") < user.index("Bàn giao")
    # no contract ⇒ no line
    assert "Bàn giao" not in build_team_step_messages(step_title="Tra cứu")[1]["content"]
