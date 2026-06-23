"""Typed settings loaded from the environment (.env via python-dotenv).

Secrets and runtime flags come from env only (code-standards.md §4). The agent
itself holds the OpenRouter key + guardrail flags; Atlassian/Slack tokens live in
their MCP servers and GitHub auth is via `gh`, so they are intentionally absent here.

Validation is lazy: missing secrets raise only when actually needed (e.g. when an
LLM call is made), not at import time, so guardrail/unit code runs without a key.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Repo root = three levels up from this file (src/config/settings.py).
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / ".data"

# OpenRouter is OpenAI-compatible; base URL is fixed by the provider.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "minimax/minimax-m2.7"


@dataclass(frozen=True)
class Settings:
    """Resolved runtime configuration.

    Build via `build_settings_from_env()` (env-loaded) or `build_settings_from_dict()`
    (pure) in `config_builders`, then inject it where needed — there is no module
    singleton; collaborators receive `Settings` as a parameter.
    """

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
