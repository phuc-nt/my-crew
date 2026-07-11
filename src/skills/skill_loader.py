"""Load a domain pack's bundled skills (v2 M3-P10; v3 M5 S5 = pack asset).

Each skill is a `<name>.md` with a `---`-delimited YAML frontmatter (`name`,
`description`, optional `applies_to`, optional `allowed-tools` — the last is
PARSED-AND-IGNORED this round) followed by the markdown instruction body. A malformed
file (no frontmatter, bad YAML, missing name/description) is SKIPPED with a warning —
one bad file never aborts the scan.

The skill `.md` files moved from the repo-root `skills/` into the owning domain pack
(`domain-packs/<domain>-pack/skills/`) in v3 M5 S5, so each domain bundles its own
skills without the core enumerating them. `load_skills(domain=...)` resolves the active
pack's dir; `domain` defaults to "pm" so the pre-v3 PM skill pool loads unchanged.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from src.skills.models import Skill

logger = logging.getLogger(__name__)

#: Charset a per-agent skill NAME may use. Names come from gitignored user-data/templates
#: (v19), so — unlike pack skills — they must not carry structural characters that could
#: forge a prompt tag. A name failing this is rejected (the skill is dropped, not silently
#: renamed-to-garbage). Vietnamese letters + digits + space/underscore/hyphen, 1-64 chars.
_AGENT_SKILL_NAME_RE = re.compile(r"^[0-9A-Za-zÀ-ỹà-ỹ _-]{1,64}$")


def load_skills(skills_dir: Path | None = None, *, domain: str = "pm") -> list[Skill]:
    """Scan a domain pack's skills dir → the Skills it holds.

    `skills_dir` overrides the location (tests pass a tmp dir); otherwise the active
    `domain`'s pack skills dir is used. Returns sorted by name (deterministic), with
    names UNIQUE: if two files declare the same `name`, the first by filename order wins
    and later duplicates are warned + dropped. Malformed files are skipped, never raised.
    """
    if skills_dir is not None:
        base = skills_dir
    else:
        from src.packs.registry import pack_skills_dir

        base = pack_skills_dir(domain)
    if not base.exists():
        return []
    by_name: dict[str, Skill] = {}
    for path in sorted(base.glob("*.md")):
        skill = _load_one(path)
        if skill is None:
            continue
        if skill.name in by_name:
            logger.warning("skill %s skipped: duplicate name %r", path.name, skill.name)
            continue
        by_name[skill.name] = skill
    return sorted(by_name.values(), key=lambda s: s.name)


def load_agent_skills(skills_dir: Path) -> list[Skill]:
    """Load an agent's OWN skills from `profiles/<id>/skills/` (v19, LOWER trust tier).

    Same frontmatter format as pack skills, but two guards apply because the source is
    gitignored user-data/templates, not repo-vetted code (red-team H5/H6):
      - the NAME must pass `_AGENT_SKILL_NAME_RE` (else the skill is dropped with a
        warning — a name with `[`/`]`/newlines could forge a prompt tag);
      - the BODY is wrapped through `format_internal_content` so an injection phrase in
        the body is delimited/spotlighted/quarantined, not executed as an instruction.

    Missing dir ⇒ []. Malformed/again-duplicate files are skipped, never raised.
    """
    if not skills_dir.exists():
        return []
    from src.tools.search_result_formatter import format_internal_content

    by_name: dict[str, Skill] = {}
    for path in sorted(skills_dir.glob("*.md")):
        skill = _load_one(path)
        if skill is None:
            continue
        if not _AGENT_SKILL_NAME_RE.match(skill.name):
            logger.warning(
                "agent skill %s skipped: name %r has disallowed characters", path.name, skill.name
            )
            continue
        if skill.name in by_name:
            logger.warning("agent skill %s skipped: duplicate name %r", path.name, skill.name)
            continue
        wrapped = format_internal_content(skill.body, label=skill.name)
        by_name[skill.name] = Skill(
            name=skill.name, description=skill.description, body=wrapped,
            applies_to=skill.applies_to,
        )
    return sorted(by_name.values(), key=lambda s: s.name)


def _load_one(path: Path) -> Skill | None:
    try:
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        name = meta.get("name")
        description = meta.get("description")
        if not name or not description:
            logger.warning("skill %s skipped: missing name/description in frontmatter", path.name)
            return None
        applies = meta.get("applies_to") or []
        applies_to = tuple(str(x) for x in applies) if isinstance(applies, list) else ()
        return Skill(
            name=str(name), description=str(description), body=body.strip(),
            applies_to=applies_to,
        )
    except Exception as exc:  # noqa: BLE001 — one bad skill file must not abort the scan
        logger.warning("skill %s skipped: %s", path.name, exc)
        return None


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split `---`-delimited YAML frontmatter from the markdown body.

    No leading `---` ⇒ ({}, text) (caller treats empty meta as malformed → skip).
    """
    if not text.lstrip().startswith("---"):
        return {}, text
    stripped = text.lstrip()
    rest = stripped[3:]  # drop the opening ---
    end = rest.find("\n---")
    if end == -1:
        return {}, text  # no closing fence → treat as no frontmatter
    front = rest[:end]
    body = rest[end + 4:]  # skip the "\n---"
    meta = yaml.safe_load(front) or {}
    if not isinstance(meta, dict):
        return {}, text
    return meta, body.lstrip("\n")
