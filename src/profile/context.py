"""Profile context → prompt injection helpers (v2 M1-P2).

Carries the three Markdown strings a profile contributes to the LLM call and the
two tiny functions that fold them into the prompt seam:

- `persona` (SOUL.md)  → PREPENDED to the system message. For an external report the
  external system prompt's PII-sanitization stays the authoritative tail, so a
  persona that names people cannot override "omit keys/PR/names" (proven by the
  guardrail test in test_audience_prompts.py).
- `project` (PROJECT.md) + `memory` (MEMORY.md) → a labeled block prepended to the
  USER message — but only for INTERNAL reports. They carry internal facts
  (milestones, conventions, reviewer names, issue keys) a stakeholder summary must
  not ground on, so they are NOT injected on the external path.

Every field defaults to "", so an empty profile yields byte-identical v1 prompts.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProfileContext:
    """The three context strings a profile injects into the prompt (all optional)."""

    persona: str = ""  # SOUL.md → system message (both audiences)
    project: str = ""  # PROJECT.md → user message (internal only)
    memory: str = ""  # MEMORY.md → user message (internal only)


#: The no-op context — used as the default everywhere so v1 behavior is unchanged.
EMPTY = ProfileContext()


def prepend_persona(system: str, persona: str) -> str:
    """Prepend the persona to a system message. Empty persona ⇒ `system` unchanged.

    The original `system` stays the authoritative tail (its rules, incl. external
    PII-sanitization, are stated AFTER the persona), so persona sets tone but cannot
    override the system's hard rules.
    """
    persona = persona.strip()
    if not persona:
        return system
    return f"{persona}\n\n{system}"


def build_context_block(project: str, memory: str) -> str:
    """Build the project+memory block to prepend to an INTERNAL user message.

    Returns "" when both are empty (⇒ user message unchanged). Never call this on the
    external path — project/memory carry internal facts a stakeholder must not see.
    """
    project = project.strip()
    memory = memory.strip()
    parts: list[str] = []
    if project:
        parts.append(f"--- Bối cảnh dự án ---\n{project}")
    if memory:
        parts.append(f"--- Bộ nhớ agent ---\n{memory}")
    if not parts:
        return ""
    return "\n\n".join(parts) + "\n\n"
