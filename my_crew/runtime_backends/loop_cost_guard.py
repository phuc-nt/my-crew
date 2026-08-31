"""Per-step spend ceiling, enforced BETWEEN loop rounds.

`cost_cap_usd` has existed on `RuntimeCaps` since v20.5 but was explicitly
observability-only: the docstring there recorded why (red-team C4) — a per-runtime number
cannot lower a shared per-task cap "without a per-agent enforcement seam that does not
exist yet". This module is that seam, for the one loop that can hold it.

**Why only the thin loop.** Enforcement has to happen where the loop can still be stopped
before the next provider call. `thin_tool_loop` owns its rounds in Python and already
accumulates per-exchange `cost_usd`, so it can check between rounds. The other two work
loops (`react_loop`, `deep_agent_loop`) hand control to LangChain's `agent.invoke` and only
learn their cost afterwards, from summed usage metadata — there is no between-iteration
point to consult, and inventing one would mean forking the community loop. So those tiers
keep their existing bound (`runtime_loop_limit`, a ROUND cap) and this cap does not claim
to cover them.

**Relationship to the task cap.** `company.team_task_cap_usd` remains the hard stop for a
whole task, enforced by the coordinator on its tick — it halts running steps and stalls the
task. This cap is narrower and earlier: it stops ONE step's loop from spending past its own
allowance, before the coordinator's next tick observes anything. Both must hold; neither
replaces the other.

**Degrade, do not fail.** Hitting the ceiling ends the loop and keeps whatever the step
already produced, with a note appended saying the work is incomplete and why. That matches
the skip-with-gap posture the fleet already takes for a non-terminal give_up: a partial
answer the reviewer can see through is worth more than an exception that discards work
already paid for. The note is written for the reviewer/CEO, so it is in Vietnamese like the
rest of the user-facing surface.
"""

from __future__ import annotations

#: Appended to the partial text when the ceiling stops a loop. Phrased as an admission of
#: incompleteness rather than an error: downstream `self_check` grades this text against the
#: step's acceptance criteria, and it must be able to tell that coverage is missing BECAUSE
#: the budget ran out, not because the agent judged the work done.
COST_CAP_GAP_NOTE = (
    "[Kết quả CHƯA hoàn chỉnh — bước đã chạm trần chi phí ${cap:.4f} "
    "(đã chi ${spent:.4f} sau {rounds} vòng công cụ) nên vòng lặp dừng sớm. "
    "Phần trên là những gì đã làm được; phần còn thiếu chưa được thực hiện.]"
)

#: Rule placed between the recovered partial work and the note. Only used when there IS
#: partial work above it — a capped loop that never produced prose would otherwise open
#: with a horizontal rule separating nothing.
_GAP_NOTE_SEPARATOR = "\n\n---\n"


def over_cost_cap(costs: list[float], cap: float | None) -> bool:
    """Has this loop's recorded spend reached its ceiling?

    `cap=None` (every tier's default) ⇒ always False, which is what keeps the feature off
    by default and makes the whole guard a no-op for fleets that never configure it. That
    is deliberately the ONLY kill-switch: an env var would be a second way to say the same
    thing, and a cap nobody set is already unlimited.

    Uses `>=` rather than `>`: at exactly the cap the allowance is spent, and the next round
    would go over it. The check is asked BEFORE a call, so it must answer "can I afford
    another one", not "have I already overshot".
    """
    if cap is None:
        return False
    return sum(costs) >= cap


def with_cost_cap_gap_note(
    partial: str, costs: list[float], cap: float, rounds: int
) -> str:
    """`partial` plus the note explaining that the ceiling cut the loop short.

    Takes the partial text rather than returning the note alone so the separator rule is
    decided here: a capped loop often has no prose to recover at all (every assistant turn
    carried tool calls, so every one had empty content), and in that case the note must be
    the whole answer, not a horizontal rule followed by the note.
    """
    note = COST_CAP_GAP_NOTE.format(cap=cap, spent=sum(costs), rounds=rounds)
    partial = partial.strip()
    return partial + _GAP_NOTE_SEPARATOR + note if partial else note
