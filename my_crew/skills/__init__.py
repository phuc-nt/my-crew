"""PM skill system (v2 M3-P10) — bundled markdown instructions for report compose.

A skill = a `SKILL.md` (YAML frontmatter + markdown body) of PM guidance. An injectable
LLM selector picks relevant skills before compose; their bodies inject into the INTERNAL
report prompt only (external takes nothing — the P5 red line). This package holds the
data model + loader; the bundled skills live in the top-level `skills/` data dir.
"""
