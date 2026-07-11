"""Memory provider protocol + config + resolver (v19).

`resolve_memory_text(loaded)` is the ONE function the prompt call-sites use. It dispatches
on `loaded.memory_config.provider`:
  - "static" → the verbatim MEMORY.md (`LoadedProfile.memory`); byte-identical pre-v19.
  - "kioku"  → RuntimeError (DEFERRED to v19.5 — see module docstring in `src/memory`).
  - anything else → RuntimeError (fail-loud; a typo must never silently disable memory).

Schema errors raise `RuntimeError` (NOT ValueError) to match the loader's `_parse_*`
convention — the entrypoints catch `(FileNotFoundError, RuntimeError)`, so a ValueError
would escape as an unhandled traceback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.profile.loader import LoadedProfile


@dataclass(frozen=True)
class MemoryConfig:
    """Parsed `memory:` block from profile.yaml. Absent ⇒ MemoryConfig() (static)."""

    provider: str = "static"


@runtime_checkable
class MemoryProvider(Protocol):
    """A source of an agent's injectable memory text + a sink for new facts.

    v19 only exercises `load_context`; `record` exists for the v19.5 kioku write hook and
    is a no-op for the static provider (MEMORY.md is curated by hand, never auto-appended).
    """

    def load_context(self, loaded: LoadedProfile) -> str:
        """Return the memory text to inject into the internal user message ("" ⇒ none)."""
        ...

    def record(self, loaded: LoadedProfile, text: str) -> None:
        """Persist a new fact. No-op for static; the kioku write hook lands in v19.5."""
        ...


def parse_memory_config(raw: object) -> MemoryConfig:
    """Validate the optional `memory:` block. Absent/empty ⇒ static (default).

    Fail-loud (RuntimeError) on shape errors so a typo can't silently pick a provider or
    disable memory. Only the `provider` key is recognised in v19.
    """
    if raw is None or raw == {} or raw == "":
        return MemoryConfig()
    if not isinstance(raw, dict):
        raise RuntimeError("profile memory: must be a mapping {provider: static|kioku}.")
    provider = str(raw.get("provider") or "static").strip() or "static"
    if provider not in {"static", "kioku"}:
        raise RuntimeError(
            f"profile memory: unknown provider {provider!r} (known: static, kioku)."
        )
    return MemoryConfig(provider=provider)


def resolve_memory_text(loaded: LoadedProfile) -> str:
    """Resolve an agent's injectable memory text per its configured provider.

    The one call the six prompt sites use instead of `loaded.memory`. Static returns the
    verbatim MEMORY.md; kioku raises (v19.5); an unknown provider raises. Raising rather
    than degrading is deliberate — an operator who set `provider: kioku` must learn it is
    not wired yet, not silently get static.
    """
    # Imported lazily to keep this module import-light and avoid a cycle with static_provider.
    from src.memory.static_provider import StaticMemoryProvider

    # `getattr` default keeps pre-v19 LoadedProfile stand-ins (that predate memory_config)
    # working: absent config ⇒ static, i.e. the historical behavior.
    config = getattr(loaded, "memory_config", None) or MemoryConfig()
    provider = config.provider
    if provider == "static":
        return StaticMemoryProvider().load_context(loaded)
    if provider == "kioku":
        raise RuntimeError(
            "memory provider 'kioku' chưa hỗ trợ (dời sang v19.5 — my-kioku adapter). "
            "Đặt memory.provider: static hoặc bỏ block memory: trong profile.yaml."
        )
    raise RuntimeError(f"memory provider {provider!r} không hợp lệ (known: static, kioku).")
