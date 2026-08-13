"""The real `judge_stuck_step` seam — one LLM call that rules on a step which finished
but failed its own acceptance criteria.

Kept out of `team_tick_collaborators.py` (already at the repo's ~200 LOC guideline) and
out of `team_tick_runner.py` for the same reason. Same shape as `make_aggregate`: a
factory closing over the coordinator's `settings`, its own `LlmClient`, and a
never-raises posture — the caller (`coordinator_nodes.stuck_decision._judge`) treats any
exception as `give_up`, so a failure here concludes the task honestly rather than
wedging it.

No API key configured ⇒ this returns `None` and the caller degrades to `give_up`. That
is deliberate: with no model there is no way to tell "fixable with direction" from
"genuinely impossible", and guessing "retry" would spend the intervention budget
relearning the same failure.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Ids the judge may hand the step to. Excludes the current assignee (already failed at
#: it) — computed per call, since a reassign is only useful toward SOMEONE ELSE.
_MAX_ROSTER = 20


def _reassign_candidates(current: str) -> list[str]:
    """`agent_id (domain)` strings for everyone who could take this step over, minus
    whoever is holding it now. Read failures degrade to an empty roster: no candidates
    simply means the judge can only choose retry or give_up, which is the right,
    conservative outcome when we cannot read who exists."""
    try:
        from my_crew.agent.team_task_roster import assignable_staff

        return [
            f"{agent_id} ({domain})"
            for agent_id, domain in assignable_staff()
            if agent_id != current
        ][:_MAX_ROSTER]
    except Exception:  # noqa: BLE001 — roster is advisory to the prompt; code re-gates it
        logger.exception("team-tick: could not read roster for stuck judgement")
        return []


def make_judge_stuck_step(settings: Any):
    """Build the `CoordinatorDeps.judge_stuck_step` callable.

    Returns `None` (⇒ caller gives up with a stated reason) when there is no API key,
    when the completion is empty, or when the verdict does not parse — every one of
    those is "we could not form a judgement", never "try again".
    """

    def _judge(brief: str, step: Any):
        from my_crew.llm.stuck_judgement_prompt import (
            StuckVerdictError,
            build_stuck_judge_messages,
            parse_stuck_verdict,
        )

        if not settings.openrouter_api_key:
            return None
        from my_crew.llm.client import LlmClient

        roster = _reassign_candidates(getattr(step, "assigned_to", "") or "")
        client = LlmClient(settings)
        result = client.complete(build_stuck_judge_messages(brief, roster), role="review")
        try:
            verdict = parse_stuck_verdict(result.content or "")
        except StuckVerdictError:
            logger.warning(
                "team-tick: unparseable stuck judgement for step %s",
                getattr(step, "step_id", ""),
            )
            return None
        return {
            "decision": verdict.decision,
            "guidance": verdict.guidance,
            "assign_to": verdict.assign_to,
            "reason": verdict.reason,
        }

    return _judge
