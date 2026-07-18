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

from my_crew.skills.skill_loader import load_skills

if TYPE_CHECKING:
    from my_crew.config.settings import Settings
    from my_crew.profile.loader import LoadedProfile
    from my_crew.skills.models import Skill
    from my_crew.skills.skill_selector import SkillSelector

logger = logging.getLogger(__name__)


def load_skill_pool(
    skill_names: tuple[str, ...],
    *,
    domain: str = "pm",
    profile_id: str | None = None,
    profiles_dir=None,
    template_role: str | None = None,
) -> tuple[Skill, ...]:
    """Load a profile's declared pack skills, its role TEMPLATE skills (v36 live-load),
    PLUS its own `profiles/<id>/skills/` (v19).

    Three sources, decreasing trust:
      1. Pack skills — repo-vetted, loaded by declared `skills:` name.
      2. Template skills (v36 P2) — when `template_role` is set, the role template's
         `profiles/templates/<role>/skills/*.md` are loaded LIVE each run (repo-vetted =
         committed data, so NOT body-scrubbed like agent-own). A template edit reaches
         every agent of that role with no re-scaffold. Agents created before live-skills
         (no `template_role`) skip this — their copied skills load as agent-own below.
      3. Per-agent skills — lower trust (body-wrapped, name-scrubbed in
         `load_agent_skills`), ALWAYS included when present.

    Override rules: an agent-own skill whose name matches a TEMPLATE skill WINS (local
    customization must beat the shared template) — the template copy is dropped. But a
    per-agent skill matching a PACK skill is NOT allowed to shadow it (red-team M4): it is
    re-exposed as `agent:<name>` so both survive.

    Empty everything ⇒ `()` with no LLM construction downstream. A named-but-missing pack
    skill is warned and dropped (a typo must not crash a run).
    """
    pack_by_name = {s.name: s for s in load_skills(domain=domain)} if skill_names else {}
    pool: list[Skill] = []
    for name in skill_names:
        skill = pack_by_name.get(name)
        if skill is None:
            logger.warning("profile skill %r not found among bundled skills; skipped", name)
            continue
        pool.append(skill)

    template_by_name: dict[str, Skill] = {}
    if template_role:
        template_by_name = _load_template_skills(template_role)

    agent_own_names: set[str] = set()
    if profile_id is not None:
        from my_crew.packs.registry import profile_skills_dir
        from my_crew.skills.models import Skill as _Skill
        from my_crew.skills.skill_loader import load_agent_skills

        pack_names = set(pack_by_name)
        for skill in load_agent_skills(profile_skills_dir(profile_id, profiles_dir=profiles_dir)):
            name = skill.name
            agent_own_names.add(skill.name)
            if name in pack_names:
                name = f"agent:{skill.name}"
                logger.info(
                    "agent skill %r collides with a pack skill; exposed as %r (no shadow)",
                    skill.name, name,
                )
                skill = _Skill(name=name, description=skill.description,
                               body=skill.body, applies_to=skill.applies_to)
            pool.append(skill)

    # Template skills load AFTER agent-own so an agent-own skill of the same name wins:
    # skip any template skill the agent has locally overridden. Also skip names already
    # taken by a pack skill (pack is the higher-trust source of that name).
    for name, skill in template_by_name.items():
        if name in agent_own_names or name in pack_by_name:
            logger.info("template skill %r overridden locally; using the local copy", name)
            continue
        pool.append(skill)

    return tuple(pool)


def _load_template_skills(template_role: str) -> dict[str, Skill]:
    """Role template skills loaded LIVE from `profiles/templates/<role>/skills/` (v36 P2).

    Loaded as repo-vetted (via `load_skills`, NOT the scrubbed agent loader) because a
    committed template is trusted code, ranking with pack skills. A missing/renamed
    template dir ⇒ {} + WARNING (fail-open to fewer skills, never a crash)."""
    from my_crew.packs.registry import SHIPPED_ROOT

    skills_dir = SHIPPED_ROOT / "profiles" / "templates" / template_role / "skills"
    if not skills_dir.is_dir():
        logger.warning(
            "template_role %r has no skills dir at %s; no template skills loaded",
            template_role, skills_dir,
        )
        return {}
    return {s.name: s for s in load_skills(skills_dir=skills_dir)}


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
        template_role=getattr(loaded, "template_role", None),
    )
    if not pool:
        return (), None
    from my_crew.llm.client import LlmClient
    from my_crew.skills.skill_selector import make_llm_selector

    return pool, make_llm_selector(LlmClient(settings))
