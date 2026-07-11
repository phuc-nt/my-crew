"""Memory provider seam (v19).

An agent's long-term memory text is injected into the INTERNAL user message (see
`src/profile/context.py::build_context_block`). Historically that text was always the
verbatim `MEMORY.md` (`LoadedProfile.memory`). v19 introduces a seam so the source can
be swapped per-agent via `profile.yaml`'s `memory:` block without touching the six
prompt call-sites.

v19 ships exactly one working provider — `static` (MEMORY.md, byte-identical to pre-v19).
The `kioku` provider (my-kioku subprocess) is DEFERRED to v19.5; selecting it raises
loudly so an operator who opts in knows it is not yet wired (never a silent fallback to
static).

The single public entry point is `resolve_memory_text(loaded)` — call it instead of
reading `loaded.memory` directly.
"""

from __future__ import annotations

from src.memory.provider import MemoryConfig, MemoryProvider, resolve_memory_text

__all__ = ["MemoryConfig", "MemoryProvider", "resolve_memory_text"]
