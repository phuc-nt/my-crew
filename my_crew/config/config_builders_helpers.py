"""Dict-coercion helpers shared by the config builders (v2 M1-P1).

Same semantics as the old `settings._env_bool`/`_env_float` but dict-keyed, so a
profile that passes `"true"` and a caller that passes `True` both work. Kept in a
tiny module so the settings + reporting builder files share one source.
"""

from __future__ import annotations

from typing import Any

_TRUE_STRINGS = {"true", "1", "yes", "on"}


def _d_bool(d: dict[str, Any], key: str, default: bool) -> bool:
    """Read a bool from the dict. Accepts a real bool or a true/1/yes/on string."""
    val = d.get(key)
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in _TRUE_STRINGS


def _d_float(d: dict[str, Any], key: str, default: float) -> float:
    val = d.get(key)
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return default
    try:
        return float(val)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Config key {key}={val!r} is not a valid float") from exc


def _d_int(d: dict[str, Any], key: str, default: int) -> int:
    val = d.get(key)
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return default
    try:
        return int(val)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Config key {key}={val!r} is not a valid int") from exc


def _d_str_or_none(d: dict[str, Any], key: str) -> str | None:
    """Empty/missing string → None (matches the v1 `os.getenv(...) or None`)."""
    val = d.get(key)
    return str(val) if val else None
