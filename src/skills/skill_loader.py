"""Load bundled PM skills from the `skills/` data dir (v2 M3-P10).

Each skill is a `skills/<name>.md` with a `---`-delimited YAML frontmatter
(`name`, `description`, optional `applies_to`, optional `allowed-tools` — the last is
PARSED-AND-IGNORED this round) followed by the markdown instruction body. A malformed
file (no frontmatter, bad YAML, missing name/description) is SKIPPED with a warning —
one bad file never aborts the scan.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from src.config.settings import REPO_ROOT
from src.skills.models import Skill

logger = logging.getLogger(__name__)

BUNDLED_SKILLS_DIR = REPO_ROOT / "skills"


def load_skills(skills_dir: Path | None = None) -> list[Skill]:
    """Scan `skills_dir` (default: the bundled `skills/`) → the Skills it holds.

    Returns sorted by name (deterministic), with names UNIQUE: if two files declare the
    same `name`, the first by filename order wins and later duplicates are warned + dropped
    (a duplicate name would otherwise inject the same skill twice). Malformed files are
    skipped, never raised.
    """
    base = skills_dir if skills_dir is not None else BUNDLED_SKILLS_DIR
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
