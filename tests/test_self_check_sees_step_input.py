"""The self-check grader is shown the step's INPUT, not just its output.

The production failure this locks down: `research_prices` was dropped after four
interventions and delivered the standard placeholder — "KHÔNG CÓ KẾT QUẢ … TUYỆT ĐỐI
không được suy diễn/ước lượng/bịa kết quả thay cho bước này". The dependent step read
that, then produced a full market table — price bands per tier, named sources (CBRE
Q3/2024, JLL Q2/2024, DKRA), even a source-reliability rating — all invented, with the
rent figures off by roughly a thousandfold. It graded itself passed and the work flowed
on toward a report for the CEO.

The rule against fabricating was already in both the work prompt and the handoff text.
It did not hold, and could not be caught afterwards: `build_self_check_messages` was
given only `result_text` and `acceptance`. A grader that never sees what the step was
given cannot tell a sourced number from an invented one — the two look identical.

So these tests pin the wiring, not the model's judgement: the input must reach the
grader, carry its own boundary, and the prompt must direct that fabrication be failed.
"""

from __future__ import annotations

from my_crew.llm.team_task_check_prompt import (
    build_rework_messages,
    build_self_check_messages,
)

_DROPPED = (
    "KHÔNG CÓ KẾT QUẢ — bước này đã bị chủ động bỏ qua, không tạo ra bất kỳ dữ liệu "
    "hay số liệu nào."
)
#: Trimmed from the real fabricated artifact (step-307.json).
_FABRICATED = (
    "| Hạng A | 3.200–6.100 USD/m²/tháng | Trung tâm quận 1 | CBRE Q3/2024 |\n"
    "| Hạng B | 1.600–3.200 USD/m²/tháng | Quận 2, quận 7 | JLL Việt Nam Q2/2024 |"
)


def _user_message(**kwargs) -> str:
    messages = build_self_check_messages(
        result_text=_FABRICATED, acceptance="Bảng so sánh có số liệu và nguồn", **kwargs
    )
    return messages[1]["content"]


def test_the_input_reaches_the_grader():
    """Without this the grader is blind to provenance and the whole check is cosmetic."""
    user = _user_message(handoff=_DROPPED)
    assert "KHÔNG CÓ KẾT QUẢ" in user, (
        "the grader was not shown that its input was empty — it cannot detect fabrication"
    )


def test_the_input_is_labelled_as_the_input():
    """Provenance only helps if the model can tell which block is which. The label must
    mark it as what the step RECEIVED, distinct from what it produced."""
    user = _user_message(handoff=_DROPPED)
    assert "ĐẦU VÀO" in user
    assert user.index("ĐẦU VÀO") < user.index("kết quả cần thẩm định"), (
        "the input must be presented before the output it is meant to justify"
    )


def test_the_input_gets_its_own_boundary():
    """Upstream content is untrusted — it may carry an injection phrase absorbed from a
    web result. Merging it into the result's wrapper would let it borrow that framing."""
    user = _user_message(handoff=_DROPPED)
    assert "KHÔNG CÓ KẾT QUẢ" in user and _FABRICATED in user
    result_at, handoff_at = user.index(_FABRICATED), user.index("KHÔNG CÓ KẾT QUẢ")
    between = user[min(result_at, handoff_at):max(result_at, handoff_at)]
    assert "ĐẦU VÀO" in between or "kết quả cần thẩm định" in between, (
        "no delimiter separates the provided input from the produced output"
    )


def test_the_grader_is_told_to_fail_unsourced_figures():
    """Wiring alone is inert: the prompt has to say what to DO with the input."""
    system = build_self_check_messages(
        result_text="x", acceptance="y", handoff=_DROPPED
    )[0]["content"]
    assert "KHÔNG CÓ KẾT QUẢ" in system, "the dropped-step case is not called out"
    assert "passed=false" in system, "the grader is not told to fail fabricated results"


def test_the_fix_attempt_also_sees_the_input():
    """Catching the fabrication is only half of it. A rework told "these figures are
    invented", without being shown that its source was empty, invents a different set
    and fails the same way — burning the rework budget to arrive back where it started."""
    messages = build_rework_messages(
        brief="Tổng hợp bảng so sánh", prior_output=_FABRICATED,
        failures=["Số liệu và nguồn không truy được về đầu vào"], handoff=_DROPPED,
    )
    user = messages[1]["content"]
    assert "KHÔNG CÓ KẾT QUẢ" in user, "the fix attempt is blind to its own input"
    assert user.index("ĐẦU VÀO") < user.index(_FABRICATED)
    assert "KHÔNG phải thay bằng một bộ số khác" in messages[0]["content"], (
        "nothing tells the rework that removing the invention is the fix, not replacing it"
    )


def test_a_first_step_is_graded_as_before():
    """A step with no deps has no input to check against. It must not gain an empty
    block that reads like 'you were given nothing', which would invite false failures."""
    user = _user_message()
    assert "ĐẦU VÀO" not in user
    assert _FABRICATED in user, "output-only grading must still work"
