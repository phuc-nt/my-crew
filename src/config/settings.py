"""Typed settings loaded from the environment (.env via python-dotenv).

Secrets and runtime flags come from env only (code-standards.md §4). The agent
itself holds the OpenRouter key + guardrail flags; Atlassian/Slack tokens live in
their MCP servers and GitHub auth is via `gh`, so they are intentionally absent here.

Validation is lazy: missing secrets raise only when actually needed (e.g. when an
LLM call is made), not at import time, so guardrail/unit code runs without a key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Repo root = three levels up from this file (src/config/settings.py).
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / ".data"

# OpenRouter is OpenAI-compatible; base URL is fixed by the provider.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "minimax/minimax-m2.7"


def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean env var. Accepts true/1/yes/on (case-insensitive)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Env var {name}={raw!r} is not a valid float") from exc


@dataclass(frozen=True)
class Settings:
    """Resolved runtime configuration. Build via `get_settings()`."""

    openrouter_api_key: str | None
    openrouter_model: str
    openrouter_referer: str
    openrouter_title: str

    dry_run: bool
    write_disabled: bool

    monthly_budget_usd: float
    budget_warn_ratio: float

    data_dir: Path

    def require_api_key(self) -> str:
        """Return the OpenRouter key, or raise a clear error if it is unset.

        Called at the point of an LLM request so non-LLM code (guardrails,
        graph build) works without a configured key.
        """
        if not self.openrouter_api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Add it to .env "
                "(copy from config.example.env)."
            )
        return self.openrouter_api_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load .env once and return cached, typed settings."""
    load_dotenv(REPO_ROOT / ".env")
    return Settings(
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY") or None,
        openrouter_model=os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL),
        openrouter_referer=os.getenv(
            "OPENROUTER_REFERER", "https://github.com/local/my-project-manager"
        ),
        openrouter_title=os.getenv("OPENROUTER_TITLE", "my-project-manager"),
        dry_run=_env_bool("DRY_RUN", default=True),
        write_disabled=_env_bool("AGENT_WRITE_DISABLED", default=False),
        monthly_budget_usd=_env_float("MONTHLY_BUDGET_USD", default=50.0),
        budget_warn_ratio=_env_float("BUDGET_WARN_RATIO", default=0.8),
        data_dir=DATA_DIR,
    )
