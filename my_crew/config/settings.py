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
from pathlib import Path

# Repo root = three levels up from this file (my_crew/config/settings.py). For an
# installed wheel this resolves into site-packages — only shipped resources (packs,
# templates, examples) may be read relative to it, never user state.
REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_home(env_value: str | None, repo_root: Path) -> Path:
    """Root for user state (.env, registry.yaml, company.yaml, profiles/, .data/).

    Resolution order: MY_CREW_HOME env > git checkout (repo-local state, unchanged
    operator/dev behavior) > ~/.my-crew (installed package — site-packages must
    never hold user data). Pure so tests can exercise the order directly.
    """
    if env_value:
        return Path(env_value).expanduser()
    if (repo_root / ".git").exists():
        return repo_root
    return Path.home() / ".my-crew"


MY_CREW_HOME = resolve_home(os.environ.get("MY_CREW_HOME"), REPO_ROOT)
DATA_DIR = MY_CREW_HOME / ".data"

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

    # v30 autonomy-first: "autonomous" (default) executes Lớp B / allowlist-miss actions
    # immediately with an audit record; "guarded" keeps the human approval queue. Lớp A
    # hard-deny, audit, dedup, dry-run and kill-switch apply in BOTH modes. Validated in
    # `build_settings_from_dict`; the gateway reads it lazily so duck-typed test stubs
    # without the field keep working on paths that never reach the interrupt branch.
    trust_mode: str = "autonomous"

    # M2-P8 runtime infra (opt-in; defaults keep the self-contained local install).
    # checkpointer / store: "sqlite"|"postgres" and "memory"|"postgres". Postgres needs
    # postgres_dsn. The graph state checkpointer + cross-thread memory Store select off
    # these — SQLite + in-memory Store are the defaults (no infra dependency).
    checkpointer: str = "sqlite"
    store: str = "memory"
    postgres_dsn: str | None = None

    # M3-P12 (B4): opt-in LangSmith tracing. Default OFF ⇒ no callbacks attached at
    # invoke time ⇒ byte-identical to pre-P12. Effective only when the env is also
    # configured (LANGCHAIN_TRACING_V2 / LANGSMITH_API_KEY) — see runtime.run_config.
    tracing: bool = False

    # v4 M9: ordered model fallback chain. Empty (default) ⇒ single-model behavior,
    # byte-identical to pre-v4. When set, entry 0 is the primary and later entries are
    # tried in order on a provider failure (402/429/5xx/timeout/empty) — the decision
    # table lives in `llm/fallback_policy.py`. The budget cap stays supreme: it is
    # re-checked before every attempt, so a fallback can never spend past the cap.
    model_chain: tuple[str, ...] = ()

    # Optional web-search provider keys for the coordinator's team-task search_hook
    # (`tools/web_search_tool.py`). Both absent ⇒ `WebSearchConfig.available()` is
    # False and the hook degrades to a no-op — no crash, no key required to run.
    tavily_api_key: str | None = None
    brave_api_key: str | None = None
    # v20.5: Firecrawl self-host (web scrape → markdown). base_url absent ⇒ FirecrawlConfig
    # .available() is False and the scrape tool degrades to a no-op (Docker offline / not
    # deployed) — no crash, no key required to run. api_key is a self-host dummy.
    firecrawl_base_url: str | None = None
    firecrawl_api_key: str | None = None

    def effective_model_chain(self) -> tuple[str, ...]:
        """The chain `LlmClient.complete` walks: declared chain, or just the model."""
        return self.model_chain or (self.openrouter_model,)

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
