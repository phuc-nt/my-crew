"""The `Skill` data model (v2 M3-P10)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Skill:
    """One bundled PM skill: frontmatter metadata + a markdown instruction body.

    `applies_to` is a SOFT hint to the LLM selector (which report kinds it suits) — the
    selector stays authoritative and may pick a skill outside its `applies_to`. There is
    NO `allowed-tools`/authority field: skills are instruction-only this round (C1); any
    `allowed-tools` frontmatter is parsed-and-ignored.
    """

    name: str
    description: str
    body: str
    applies_to: tuple[str, ...] = ()
