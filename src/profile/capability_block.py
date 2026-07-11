"""Auto-generated agent capability block (v19 workspace protocol).

The "TOOLS.md-equivalent" of the OpenClaw/hermes file protocol — but generated at runtime
from the pack + profile, so the operator never hand-maintains it. It is a deterministic,
sorted, ≤600-char Vietnamese summary of what an agent CAN do: its domain, report kinds,
skill names, web-search flag, and memory provider.

RED LINE (red-team H6): this block is INTERNAL-ONLY. It rides the `build_context_block`
user-message path (gated on `audience == "internal"`), NEVER the system message — the
system message serves BOTH audiences, and skill names are free text from gitignored
user-data. External stakeholder deliverables get zero bytes of it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.packs.registry import Pack
    from src.profile.loader import LoadedProfile

_MAX_CHARS = 600


def build_capability_block(loaded: LoadedProfile, pack: Pack | None) -> str:
    """Return the capability summary text for an agent, or "" when nothing to say.

    Deterministic (sorted keys), so a pin test can assert it byte-for-byte. Skill names
    come pre-scrubbed from the pool the caller passes via `skill_names`; here we take the
    profile's declared `skills:` plus any resolved pool names the caller threads in.
    """
    lines: list[str] = []
    domain = getattr(loaded, "domain", "pm")
    lines.append(f"- Lĩnh vực: {domain}")

    if pack is not None and getattr(pack, "report_kinds", None):
        kinds = ", ".join(sorted(pack.report_kinds))
        lines.append(f"- Loại báo cáo: {kinds}")

    skills = getattr(loaded, "skills", ())
    if skills:
        lines.append(f"- Kỹ năng: {', '.join(sorted(skills))}")

    if getattr(loaded, "web_search", False):
        lines.append("- Tra cứu web: bật")

    provider = getattr(getattr(loaded, "memory_config", None), "provider", "static")
    lines.append(f"- Bộ nhớ: {provider}")

    block = "--- Năng lực nhân sự ---\n" + "\n".join(lines)
    if len(block) > _MAX_CHARS:
        block = block[: _MAX_CHARS - 1].rstrip() + "…"
    return block
