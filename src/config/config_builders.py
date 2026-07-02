"""Config builders — `from_dict` core + `from_env` wrapper (v2 M1-P1).

Replaces the two `@lru_cache` config singletons. `from_dict` is PURE (dict in →
frozen dataclass out, holding all validation); `from_env` is the only place that
does I/O (`load_dotenv` + `os.environ`) and delegates to `from_dict`.

This is the contract the v2 profile loader (M1-P2) plugs into: it maps a
`profile.yaml` to these dicts and calls `from_dict`, reusing every default + the
stakeholder-channel validation. Dict keys mirror the env var names lowercased
(flat), so `from_env` is a trivial pass. The one non-1:1 name is
`AGENT_WRITE_DISABLED` → `write_disabled` (the dataclass field name).

This module holds the Settings builders + the dict-coercion helpers, and
RE-EXPORTS the ReportingConfig builders from `config_builders_reporting` so the
public import path is `from src.config.config_builders import build_*`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Re-export the dict-coercion helpers + the reporting builders (single import path).
from src.config.config_builders_helpers import (
    _d_bool,
    _d_float,  # noqa: F401  (re-exported for the reporting module + tests)
    _d_int,  # noqa: F401
    _d_str_or_none,
)
from src.config.config_builders_reporting import (
    build_reporting_config_from_dict,
    build_reporting_config_from_env,
)
from src.config.settings import DATA_DIR, DEFAULT_MODEL, Settings

__all__ = [
    "build_settings_from_dict",
    "build_settings_from_env",
    "build_reporting_config_from_dict",
    "build_reporting_config_from_env",
]


def _d_model_chain(value: Any) -> tuple[str, ...]:
    """Coerce a `model_chain` value (yaml list or comma string) to a tuple of models.

    Empty/absent ⇒ () ⇒ single-model behavior (v4 M9 backward-compat). A non-string
    entry or a blank-only value raises — a typo'd chain must fail at load, not at the
    first fallback attempt in a 3 a.m. cron run.
    """
    if value is None or value == "" or value == []:
        return ()
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
    elif isinstance(value, (list, tuple)):
        for p in value:
            if not isinstance(p, str):
                raise ValueError(
                    f"model_chain entries must be strings, got {p!r} — quote model names "
                    "in yaml (an unquoted 2.5 parses as a float)"
                )
        parts = [p.strip() for p in value]
    else:
        raise ValueError("model_chain must be a list of model names or a comma string")
    chain = tuple(p for p in parts if p)
    if not chain:
        raise ValueError("model_chain is set but contains no model names")
    return chain


def build_settings_from_dict(d: dict[str, Any]) -> Settings:
    """Build Settings from a plain dict. Pure: no env, no I/O. All keys optional."""
    data_dir = d.get("data_dir", DATA_DIR)
    return Settings(
        openrouter_api_key=_d_str_or_none(d, "openrouter_api_key"),
        openrouter_model=d.get("openrouter_model") or DEFAULT_MODEL,
        openrouter_referer=d.get("openrouter_referer")
        or "https://github.com/local/my-project-manager",
        openrouter_title=d.get("openrouter_title") or "my-project-manager",
        model_chain=_d_model_chain(d.get("model_chain")),
        dry_run=_d_bool(d, "dry_run", True),
        write_disabled=_d_bool(d, "write_disabled", False),
        monthly_budget_usd=_d_float(d, "monthly_budget_usd", 50.0),
        budget_warn_ratio=_d_float(d, "budget_warn_ratio", 0.8),
        data_dir=Path(data_dir) if not isinstance(data_dir, Path) else data_dir,
        checkpointer=(d.get("checkpointer") or "sqlite").lower(),
        store=(d.get("store") or "memory").lower(),
        postgres_dsn=_d_str_or_none(d, "postgres_dsn"),
        tracing=_d_bool(d, "tracing", False),
    )


def build_settings_from_env() -> Settings:
    """Load .env + read os.environ into a dict, then delegate to from_dict.

    Reproduces the v1 env-loaded settings exactly (same keys, same coercion).
    """
    from src.config.settings import REPO_ROOT
    from src.runtime.run_config import tracing_env_on

    load_dotenv(REPO_ROOT / ".env")
    return build_settings_from_dict(
        {
            "openrouter_api_key": os.getenv("OPENROUTER_API_KEY"),
            "openrouter_model": os.getenv("OPENROUTER_MODEL"),
            "openrouter_referer": os.getenv("OPENROUTER_REFERER"),
            "openrouter_title": os.getenv("OPENROUTER_TITLE"),
            "model_chain": os.getenv("OPENROUTER_MODEL_CHAIN"),
            "dry_run": os.getenv("DRY_RUN"),
            "write_disabled": os.getenv("AGENT_WRITE_DISABLED"),
            "monthly_budget_usd": os.getenv("MONTHLY_BUDGET_USD"),
            "budget_warn_ratio": os.getenv("BUDGET_WARN_RATIO"),
            "data_dir": DATA_DIR,
            "checkpointer": os.getenv("CHECKPOINTER_TYPE"),
            "store": os.getenv("STORE_TYPE"),
            "postgres_dsn": os.getenv("POSTGRES_DSN"),
            # Tracing is on (env side) when either the V2 flag is truthy OR an API key is
            # present — normalized to a bool so an API-key string (not a true/false word)
            # still enables. Shared helper so the worker/cli settings path and the server
            # env-only path agree on the same signal.
            "tracing": tracing_env_on(),
        }
    )
