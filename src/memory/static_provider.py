"""Static memory provider (v19) — the pre-v19 behavior, wrapped in the seam.

`load_context` returns the verbatim MEMORY.md (`LoadedProfile.memory`), so a static agent
produces a byte-identical memory slot. `record` is a no-op: MEMORY.md is curated by the
CEO/agent by hand (the M2-P8 Store `remember` node is a separate path, out of this seam),
never auto-appended by the static provider.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.profile.loader import LoadedProfile


class StaticMemoryProvider:
    """Serve MEMORY.md verbatim; ignore writes."""

    def load_context(self, loaded: LoadedProfile) -> str:
        return loaded.memory

    def record(self, loaded: LoadedProfile, text: str) -> None:  # noqa: ARG002 - Protocol shape
        """No-op: MEMORY.md is hand-curated (see module docstring)."""
        return None
