"""Skills + company docs for the team-step prompt on the tool-calling tiers.

The native tier (`team_task_graph`) and the sprint runner pass the agent's selected
skills and opted-in company docs into `build_team_step_messages`. The three tool-calling
tiers (thin loop, react loop, deep agent) reuse that same prompt builder but historically
handed it only persona/project/memory/capability — so an agent whose steps always routed
to `create_agent`/`deep_agent` never saw a single skill, and the skill curator saw every
one of its skills as "never used". This is the one place all three tiers now call.
"""

from __future__ import annotations

from my_crew.company_docs.inject import company_docs_text
from my_crew.skills.skill_selector import select_skill_text


def team_step_skills_text(context) -> str:
    """The selected skill bodies for one team step (internal audience), or "".

    Tolerates the bare contexts the loop tiers are handed in tests (no `skills` /
    `skill_selector` attributes) — "" exactly like an agent with no skill pool. Running
    the selector here also records usage for the curator when the context names its
    agent — the same side effect the native tier has always had.
    """
    if getattr(context, "skills", None) and getattr(context, "skill_selector", None) is not None:
        return select_skill_text(context, "internal", kind="team-step")
    return ""


def team_step_prompt_extras(context) -> dict[str, str]:
    """`skills=` / `company_docs=` kwargs for `build_team_step_messages` (internal audience).

    Used by the thin and react loops. The deep tier takes only `team_step_skills_text` —
    it withholds company docs on purpose (network-capable sandbox).
    """
    return {
        "skills": team_step_skills_text(context),
        "company_docs": company_docs_text(context, "internal"),
    }
