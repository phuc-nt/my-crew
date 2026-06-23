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


def build_settings_from_dict(d: dict[str, Any]) -> Settings:
    """Build Settings from a plain dict. Pure: no env, no I/O. All keys optional."""
    data_dir = d.get("data_dir", DATA_DIR)
    return Settings(
        openrouter_api_key=_d_str_or_none(d, "openrouter_api_key"),
        openrouter_model=d.get("openrouter_model") or DEFAULT_MODEL,
        openrouter_referer=d.get("openrouter_referer")
        or "https://github.com/local/my-project-manager",
        openrouter_title=d.get("openrouter_title") or "my-project-manager",
        dry_run=_d_bool(d, "dry_run", True),
        write_disabled=_d_bool(d, "write_disabled", False),
        monthly_budget_usd=_d_float(d, "monthly_budget_usd", 50.0),
        budget_warn_ratio=_d_float(d, "budget_warn_ratio", 0.8),
        data_dir=Path(data_dir) if not isinstance(data_dir, Path) else data_dir,
    )


def build_settings_from_env() -> Settings:
    """Load .env + read os.environ into a dict, then delegate to from_dict.

    Reproduces the v1 env-loaded settings exactly (same keys, same coercion).
    """
    from src.config.settings import REPO_ROOT

    load_dotenv(REPO_ROOT / ".env")
    return build_settings_from_dict(
        {
            "openrouter_api_key": os.getenv("OPENROUTER_API_KEY"),
            "openrouter_model": os.getenv("OPENROUTER_MODEL"),
            "openrouter_referer": os.getenv("OPENROUTER_REFERER"),
            "openrouter_title": os.getenv("OPENROUTER_TITLE"),
            "dry_run": os.getenv("DRY_RUN"),
            "write_disabled": os.getenv("AGENT_WRITE_DISABLED"),
            "monthly_budget_usd": os.getenv("MONTHLY_BUDGET_USD"),
            "budget_warn_ratio": os.getenv("BUDGET_WARN_RATIO"),
            "data_dir": DATA_DIR,
        }
    )
