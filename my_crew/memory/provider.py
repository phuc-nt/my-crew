"""Memory provider protocol + config + resolver (v19).

`resolve_memory_text(loaded)` is the ONE function the prompt call-sites use. It dispatches
on `loaded.memory_config.provider`:
  - "static" → the verbatim MEMORY.md (`LoadedProfile.memory`); byte-identical pre-v19.
  - "kioku"  → RuntimeError (DEFERRED to v19.5 — see module docstring in `my_crew/memory`).
  - anything else → RuntimeError (fail-loud; a typo must never silently disable memory).

Schema errors raise `RuntimeError` (NOT ValueError) to match the loader's `_parse_*`
convention — the entrypoints catch `(FileNotFoundError, RuntimeError)`, so a ValueError
would escape as an unhandled traceback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from my_crew.profile.loader import LoadedProfile


@dataclass(frozen=True)
class MemoryConfig:
    """Parsed `memory:` block from profile.yaml. Absent ⇒ MemoryConfig() (static).

    `daily_notes` (v57 P5, opt-in): sau mỗi lượt chat internal đã gửi thật, trích fact vào
    `profiles/<id>/memory/YYYY-MM-DD.md`; các ngày gần nhất được nạp lại vào context.
    Tắt (mặc định) ⇒ hành vi byte-identical pre-v57."""

    provider: str = "static"
    daily_notes: bool = False


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
    daily_notes = raw.get("daily_notes", False)
    if not isinstance(daily_notes, bool):
        raise RuntimeError("profile memory.daily_notes: phải là true/false.")
    return MemoryConfig(provider=provider, daily_notes=daily_notes)


def resolve_memory_text(loaded: LoadedProfile) -> str:
    """Resolve an agent's injectable memory text per its configured provider.

    The one call the six prompt sites use instead of `loaded.memory`. Static returns the
    verbatim MEMORY.md; kioku raises (v19.5); an unknown provider raises. Raising rather
    than degrading is deliberate — an operator who set `provider: kioku` must learn it is
    not wired yet, not silently get static.
    """
    # Imported lazily to keep this module import-light and avoid a cycle with static_provider.
    from my_crew.memory.static_provider import StaticMemoryProvider

    # `getattr` default keeps pre-v19 LoadedProfile stand-ins (that predate memory_config)
    # working: absent config ⇒ static, i.e. the historical behavior.
    config = getattr(loaded, "memory_config", None) or MemoryConfig()
    provider = config.provider
    if provider == "static":
        base = StaticMemoryProvider().load_context(loaded)
        if not config.daily_notes:
            return base  # byte-identical pre-v57 khi không opt-in
        profile_id = getattr(loaded, "profile_id", "") or ""
        if not profile_id:
            return base  # stand-in không danh tính ⇒ không có thư mục notes để nạp
        from my_crew.memory.daily_notes import recent_notes_text

        notes = recent_notes_text(profile_id)
        if not notes:
            return base
        label = "NHẬT KÝ GẦN ĐÂY (tự ghi, các ngày gần nhất):"
        return f"{base}\n\n{label}\n{notes}" if base else f"{label}\n{notes}"
    if provider == "kioku":
        raise RuntimeError(
            "memory provider 'kioku' chưa hỗ trợ (dời sang v19.5 — my-kioku adapter). "
            "Đặt memory.provider: static hoặc bỏ block memory: trong profile.yaml."
        )
    raise RuntimeError(f"memory provider {provider!r} không hợp lệ (known: static, kioku).")
