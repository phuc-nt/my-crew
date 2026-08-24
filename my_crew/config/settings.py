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


# Root for SHIPPED resources (profiles/default, profiles/templates, domain-packs/,
# registry.example.yaml, config/model_prices.yaml). A wheel bundles them under
# my_crew/_shipped/ (pyproject force-include); a checkout has no _shipped dir and
# reads them straight from the repo root.
_PACKAGED_SHIPPED = Path(__file__).resolve().parents[1] / "_shipped"
SHIPPED_ROOT = _PACKAGED_SHIPPED if _PACKAGED_SHIPPED.is_dir() else REPO_ROOT

MY_CREW_HOME = resolve_home(os.environ.get("MY_CREW_HOME"), REPO_ROOT)
# Installed-package mode needs the home to exist before the first flat-file write
# (wizard .env, registry bootstrap, .setup-complete). No-op for a checkout — the
# repo root already exists. A read-only fs must not break import; the first real
# write will surface its own clear error.
try:
    MY_CREW_HOME.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
DATA_DIR = MY_CREW_HOME / ".data"

# OpenRouter is OpenAI-compatible; base URL is fixed by the provider.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4-pro-0813"

# The work kinds a per-role model override may name (`Settings.role_models`). These are
# cost shapes, not capabilities — the split is "does a human read this output".
#   content   — writes the deliverable (team step work/rework, sprint draft+revise,
#               reports, QA answers). Never downgrade this: it IS the product.
#   review    — judges another step's output against acceptance; verdict + notes.
#   aggregate — merges finished step outputs into one summary.
#   plan      — decomposition, intake, amend, routing, skill/sibling selection.
#   util      — short mechanical calls (slot extraction, memory consolidation,
#               reflection). NOTE: the deep-agent sanitizer is deliberately NOT in
#               this bucket — it is fail-closed and gates sandbox network access, so
#               it stays on the fleet model regardless of cost.
#   advisor   — the ride-along second opinion (`runtime/advisor_sweep.py`): reads a
#               running step's transcript delta and either stays silent or emits ONE
#               short note. Unlike the others this role wants a model that is not
#               necessarily cheap — the whole point is a different, sharper reader
#               than the one doing the work.
MODEL_ROLES = ("content", "review", "aggregate", "plan", "util", "advisor")


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
    # checkpointer: "sqlite"|"postgres"; store: "sqlite"|"memory"|"postgres" (postgres
    # needs postgres_dsn). v66: the memory Store default is "sqlite" — one shared
    # cross-agent file so remembered facts persist across worker runs; "memory" keeps
    # the old per-process store, "postgres" stays the opt-in durable backend.
    checkpointer: str = "sqlite"
    store: str = "sqlite"
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

    # Per-role model overrides, as (role, model) pairs — a tuple, not a dict, because
    # this dataclass is frozen and must stay hashable. Empty (default) ⇒ every role
    # runs the fleet model, byte-identical to pre-v79.
    #
    # The point is cost shape, not capability: a review verdict or a slot extraction
    # is a short mechanical judgement, while the content step writes the artifact a
    # human reads. Paying content prices for the former is the fleet's largest avoidable
    # cost. See `model_for_role` for how an override resolves.
    role_models: tuple[tuple[str, str], ...] = ()

    # Extra OpenAI-compatible endpoints a chain entry can name with `provider::model`
    # (v91). Tuple of `(name, base_url, api_key_env)` for the same frozen/hashable
    # reason as `role_models`. Empty (default) ⇒ every entry resolves through
    # OpenRouter exactly as pre-v91.
    #
    # Only the env var NAME lives here — never the key itself — so a provider can be
    # declared in a yaml that is safe to read, while the secret stays in the process
    # environment. See `provider_for` / `require_provider_key`.
    providers: tuple[tuple[str, str, str], ...] = ()

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

    # v80 pi-sessions: per-attempt step transcript JSONL (the recorder in
    # `runtime/step_recorder.py`). Default ON — the transcript is the observability
    # keystone; turn off with STEP_TRANSCRIPTS=false to fall back to pre-v80 opacity.
    # Transcripts live under `.data/artifacts/team-tasks/<task>/transcripts/` (never
    # egressed) and are swept after 30 days by storage_hygiene.
    step_transcripts: bool = True
    # v80 P3: cap (chars) on transcript-derived process evidence injected into the
    # peer-review prompt. 0 turns the feature off entirely (review grades blind, as
    # pre-v80). The cap keeps review cheap-by-default — transcripts run 10–50× the
    # deliverable's size and must never ride into the prompt whole.
    review_transcript_evidence_max_chars: int = 8000
    # v80 P5: cap (chars) on the BEHAVIOR summary (tool names + counts only, never
    # content) injected into the coordinator's reflection prompt. 0 turns it off —
    # reflection then looks only at the structural digest, as pre-v80. Smaller than
    # the review cap on purpose: reflection wants the pattern, not the sources.
    reflection_transcript_evidence_max_chars: int = 4000
    # v80 P4: mirror live in-step activity (tool name + counter, NEVER args/results —
    # the allowlist is hard-coded in `step_recorder.ACTIVITY_FIELDS`) into the task's
    # office room. Rides the transcript recorder, so it is only effective while
    # `step_transcripts` is also on. STEP_ACTIVITY_FEED=false returns the office to
    # the pre-v80 "im lặng giữa hai step_status" behavior.
    step_activity_feed: bool = True

    # Advisor ride-along (`runtime/advisor_sweep.py`): each team tick, read what a
    # running step has newly written to its transcript and let a second model flag
    # trouble the working agent cannot see from inside its own context. Default OFF —
    # it spends an LLM call per active step per sweep, so a fleet opts in once it has
    # seen the notes are worth the money. Requires `step_transcripts` (no transcript,
    # nothing to advise on); the sweep is a no-op either flag off.
    advisor_enabled: bool = False

    def effective_model_chain(self) -> tuple[str, ...]:
        """The chain `LlmClient.complete` walks: declared chain, or just the model."""
        return self.model_chain or (self.openrouter_model,)

    def model_for_role(self, role: str) -> tuple[str, ...]:
        """The chain to run `role` on: its override first, then the fleet chain.

        Returns a CHAIN rather than a bare model so a role override never costs the
        caller its fallback — a cheap model is exactly the kind that gets rate-limited
        or 5xxs, and silently losing the fallback there would trade pennies for a dead
        step. The fleet chain is appended after the override for the same reason: when
        the cheap model is exhausted the role degrades UP to the fleet model rather
        than failing outright.

        An unknown role is not an error — it simply has no override and gets the fleet
        chain, so a call site can name a role before anyone configures a model for it.
        """
        for name, model in self.role_models:
            if name == role:
                fleet = self.effective_model_chain()
                return (model,) + tuple(m for m in fleet if m != model)
        return self.effective_model_chain()

    def provider_for(self, name: str) -> tuple[str, str]:
        """Return `(base_url, api_key_env)` for a declared provider.

        Unknown names raise rather than falling back to OpenRouter: a typo in
        `deepsek::model` that quietly billed OpenRouter for a model it does not serve
        would surface as a confusing upstream 404, not as the config error it is.
        """
        for declared, base_url, api_key_env in self.providers:
            if declared == name:
                return base_url, api_key_env
        known = ", ".join(sorted(n for n, _u, _e in self.providers)) or "(none declared)"
        raise RuntimeError(
            f"unknown model provider {name!r} — declared providers: {known}. "
            "Add it under `providers:` in company.yaml/profile.yaml."
        )

    def require_provider_key(self, name: str) -> str:
        """The API key for provider `name`, read from its declared env var.

        Names the provider AND the env var in the error, because the whole point of
        env-name indirection is that the config does not say what the variable is
        called — without both halves the operator cannot tell what to set.
        """
        _base_url, api_key_env = self.provider_for(name)
        key = os.getenv(api_key_env)
        if not key:
            raise RuntimeError(
                f"provider {name!r} needs API key in ${api_key_env}, which is not set. "
                "Add it to .env."
            )
        return key

    def require_api_key(self) -> str:
        """Return the OpenRouter key, or raise a clear error if it is unset.

        Called at the point of an LLM request so non-LLM code (guardrails,
        graph build) works without a configured key.
        """
        if not self.openrouter_api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Add it to .env "
                "(copy from .env.example)."
            )
        return self.openrouter_api_key
