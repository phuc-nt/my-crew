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

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.agent.sibling_selector import SiblingFactSelector
    from src.company_docs.store import CompanyDoc
    from src.skills.models import Skill
    from src.skills.skill_selector import SkillSelector


@dataclass(frozen=True)
class ProfileContext:
    """The three context strings a profile injects into the prompt (all optional).

    `skills` is the agent's candidate skill pool (M3-P10); `skill_selector` is the
    injectable picker. `sibling_facts` is other same-project agents' remembered facts
    (M3-P9 A3); `sibling_selector` ranks them; `sibling_project` labels the block. All
    feed the INTERNAL compose prompt only (external takes nothing — same red line as
    project/memory). Default empty ⇒ no injection.
    """

    persona: str = ""  # SOUL.md → system message (both audiences)
    project: str = ""  # PROJECT.md → user message (internal only)
    memory: str = ""  # MEMORY.md → user message (internal only)
    capability: str = ""  # v19 auto-gen capability summary → user message (internal only)
    skills: tuple[Skill, ...] = ()  # M3-P10 candidate pool (internal only)
    skill_selector: SkillSelector | None = field(default=None)  # injectable picker
    sibling_facts: tuple[str, ...] = ()  # M3-P9 sibling memory (internal only)
    sibling_selector: SiblingFactSelector | None = field(default=None)  # injectable ranker
    sibling_project: str | None = None  # label slug for the sibling block
    company_docs: tuple[CompanyDoc, ...] = ()  # M19 opted-in company docs (internal only)
    auto_approve: dict | None = None  # v8 M23 trust-ladder config (None ⇒ OFF); threaded to
    # the approval gate + the delivery gateway so a trusted scheduled report auto-delivers.


#: The no-op context — used as the default everywhere so v1 behavior is unchanged.
EMPTY = ProfileContext()


#: Strip HTML comments (the scaffolded profile placeholders like
#: `<!-- Persona. Empty ⇒ ... -->`) so a comment-only file counts as empty and never
#: leaks its meta-text into the prompt. Real persona/context text (non-comment) survives.
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _strip_meta(text: str) -> str:
    """Remove HTML comments + surrounding whitespace. A placeholder-only file → ""."""
    return _HTML_COMMENT.sub("", text).strip()


def prepend_persona(system: str, persona: str) -> str:
    """Prepend the persona to a system message. Empty persona ⇒ `system` unchanged.

    The original `system` stays the authoritative tail (its rules, incl. external
    PII-sanitization, are stated AFTER the persona), so persona sets tone but cannot
    override the system's hard rules. A scaffolded file that holds only an HTML-comment
    placeholder counts as empty (its meta-text must not reach the model).
    """
    persona = _strip_meta(persona)
    if not persona:
        return system
    return f"{persona}\n\n{system}"


def build_context_block(project: str, memory: str, capability: str = "") -> str:
    """Build the capability+project+memory block to prepend to an INTERNAL user message.

    Returns "" when all are empty (⇒ user message unchanged). Never call this on the
    external path — project/memory carry internal facts a stakeholder must not see, and
    the v19 `capability` block carries internal skill names/flags (red-team H6: it must
    NOT ride the system message, which serves both audiences). `capability` defaults to
    "" so every pre-v19 caller is byte-identical. A comment-only placeholder file counts
    as empty (no meta-text injected).
    """
    project = _strip_meta(project)
    memory = _strip_meta(memory)
    capability = capability.strip()
    parts: list[str] = []
    if capability:
        parts.append(capability)
    if project:
        parts.append(f"--- Bối cảnh dự án ---\n{project}")
    if memory:
        parts.append(f"--- Bộ nhớ agent ---\n{memory}")
    if not parts:
        return ""
    return "\n\n".join(parts) + "\n\n"
