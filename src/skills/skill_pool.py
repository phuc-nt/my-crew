"""Resolve a profile's `skills:` name list into the runtime skill context (M3-P10 S3).

The single seam the three graph-build entry points (worker / cron / cli) call to wire
skills into the `ProfileContext` they construct. `load_skill_pool` turns the candidate
NAMES (from `LoadedProfile.skills`) into the matching `Skill` objects; `build_skill_context`
pairs that pool with the default LLM selector — but ONLY when the pool is non-empty, so the
no-skills path (the default profile) never constructs an `LlmClient` and stays identical.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.skills.skill_loader import load_skills

if TYPE_CHECKING:
    from src.config.settings import Settings
    from src.profile.loader import LoadedProfile
    from src.skills.models import Skill
    from src.skills.skill_selector import SkillSelector

logger = logging.getLogger(__name__)


def load_skill_pool(
    skill_names: tuple[str, ...],
    *,
    domain: str = "pm",
    profile_id: str | None = None,
    profiles_dir=None,
) -> tuple[Skill, ...]:
    """Load a profile's declared pack skills PLUS its own `profiles/<id>/skills/` (v19).

    Pack skills (repo-vetted) load by their declared `skills:` names. Per-agent skills
    (lower trust — body-wrapped, name-scrubbed in `load_agent_skills`) are ALWAYS included
    when present. Collision rule (red-team M4): a per-agent skill whose name matches a pack
    skill is NOT allowed to shadow it — it is re-exposed as `agent:<name>` so BOTH survive
    and the vetted pack skill is never silently replaced.

    Empty `skill_names` AND no agent skills ⇒ `()` with no LLM construction downstream. A
    named-but-missing pack skill is warned and dropped (a typo must not crash a run).
    """
    pack_by_name = {s.name: s for s in load_skills(domain=domain)} if skill_names else {}
    pool: list[Skill] = []
    for name in skill_names:
        skill = pack_by_name.get(name)
        if skill is None:
            logger.warning("profile skill %r not found among bundled skills; skipped", name)
            continue
        pool.append(skill)

    if profile_id is not None:
        from src.packs.registry import profile_skills_dir
        from src.skills.models import Skill as _Skill
        from src.skills.skill_loader import load_agent_skills

        pack_names = set(pack_by_name)
        for skill in load_agent_skills(profile_skills_dir(profile_id, profiles_dir=profiles_dir)):
            name = skill.name
            if name in pack_names:
                name = f"agent:{skill.name}"
                logger.info(
                    "agent skill %r collides with a pack skill; exposed as %r (no shadow)",
                    skill.name, name,
                )
                skill = _Skill(name=name, description=skill.description,
                               body=skill.body, applies_to=skill.applies_to)
            pool.append(skill)

    return tuple(pool)


def build_skill_context(
    loaded: LoadedProfile, settings: Settings, *, profiles_dir=None
) -> tuple[tuple[Skill, ...], SkillSelector | None]:
    """Build the `(skills, selector)` pair to pass into a `ProfileContext`.

    Returns `((), None)` when the profile has neither declared pack skills nor its own
    `skills/` dir — WITHOUT constructing an `LlmClient` — so the no-skills path needs no key
    and allocates nothing new. The agent's `domain` selects which pack's skills load; its
    `profile_id` pulls in per-agent skills (body-wrapped, collision-safe).
    """
    pool = load_skill_pool(
        loaded.skills,
        domain=getattr(loaded, "domain", "pm"),
        profile_id=getattr(loaded, "profile_id", None),
        profiles_dir=profiles_dir,
    )
    if not pool:
        return (), None
    from src.llm.client import LlmClient
    from src.skills.skill_selector import make_llm_selector

    return pool, make_llm_selector(LlmClient(settings))
