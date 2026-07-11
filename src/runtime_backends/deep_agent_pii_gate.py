"""PII / audience gate for deep-agent context (v20.5 Phase 3, red-team H2/H3).

A deep agent runs shell freely inside a sandbox with free network. Even though the sandbox is
token-free, the HOST-side prompt it receives can carry internal company data (persona notes,
agent memory, company_docs) — and the agent could write that into a sandbox file and exfiltrate
it (red-team H2). To shrink that exfil surface, the deep agent runs on an EXTERNAL-audience-safe
context: the internal-only fields (memory, company_docs, capability) are withheld, exactly as an
external stakeholder report withholds them. The step title + handoff (its actual work input)
still flow, but the ambient internal context does not.

This is a deliberate trade-off, documented for the operator: a deep agent is the least-trusted
runtime, so it gets the least internal context. If a task genuinely needs internal grounding,
use the tool-calling runtime (which keeps context internal but never runs shell).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.profile.context import ProfileContext


def gate_context_for_sandbox(context: ProfileContext) -> ProfileContext:
    """Return a copy of `context` with internal-only fields stripped (external-audience-safe).

    Keeps `persona` (the role framing — needed for coherent output, same as an external report's
    system prompt keeps persona) but drops `memory`, `company_docs`, and `capability` (the
    internal facts a sandbox-with-egress must not carry).
    """
    from dataclasses import replace

    return replace(
        context,
        memory="",
        company_docs=(),
        capability="",
    )
