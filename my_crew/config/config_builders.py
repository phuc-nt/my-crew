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
public import path is `from my_crew.config.config_builders import build_*`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Re-export the dict-coercion helpers + the reporting builders (single import path).
from my_crew.config.config_builders_helpers import (
    _d_bool,
    _d_float,  # noqa: F401  (re-exported for the reporting module + tests)
    _d_int,
    _d_str_or_none,
)
from my_crew.config.config_builders_reporting import (
    build_reporting_config_from_dict,
    build_reporting_config_from_env,
)
from my_crew.config.settings import DATA_DIR, DEFAULT_MODEL, MODEL_ROLES, Settings

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


def _d_role_models(value: Any) -> tuple[tuple[str, str], ...]:
    """Coerce `role_models` (yaml mapping or "role=model,role=model" string) to pairs.

    Empty/absent ⇒ () ⇒ every role runs the fleet model. An unknown ROLE NAME raises:
    a typo'd role silently means "no override", so the operator would see the fleet
    model's bill and no error — the same 3 a.m. failure mode `_d_model_chain` guards.
    A duplicate role also raises rather than letting last-wins decide quietly.
    """
    if value is None or value == "" or value == {} or value == []:
        return ()
    if isinstance(value, str):
        entries = [p.strip() for p in value.split(",") if p.strip()]
        pairs = []
        for entry in entries:
            role, sep, model = entry.partition("=")
            if not sep or not role.strip() or not model.strip():
                raise ValueError(
                    f"role_models entry must be 'role=model', got {entry!r} "
                    "(OPENROUTER_ROLE_MODELS in .env)"
                )
            pairs.append((role.strip(), model.strip()))
    elif isinstance(value, dict):
        pairs = []
        for role, model in value.items():
            if not isinstance(model, str) or not model.strip():
                raise ValueError(
                    f"role_models[{role!r}] must be a model name string, got {model!r} "
                    "— quote model names in yaml"
                )
            pairs.append((str(role).strip(), model.strip()))
    else:
        raise ValueError("role_models must be a mapping or a 'role=model,...' string")

    seen: set[str] = set()
    for role, _model in pairs:
        if role not in MODEL_ROLES:
            raise ValueError(
                f"unknown role_models key {role!r} — valid roles are "
                f"{', '.join(sorted(MODEL_ROLES))}"
            )
        if role in seen:
            raise ValueError(f"role_models declares {role!r} twice")
        seen.add(role)
    return tuple(pairs)


# A provider name is the prefix in `name::model`, so it must not contain `:` or `/`,
# both of which already carry meaning in model ids. An api_key_env is an environment
# variable NAME — the shape check is what stops a real key being pasted into yaml.
_PROVIDER_NAME_RE = re.compile(r"[a-z0-9-]+")
_ENV_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]*")


def _d_providers(value: Any) -> tuple[tuple[str, str, str], ...]:
    """Coerce `providers` to `(name, base_url, api_key_env)` triples.

    Two input shapes, mirroring `_d_role_models`: a yaml mapping
    `{name: {base_url, api_key_env}}`, or the env string form
    `"name=base_url|API_KEY_ENV,..."` for a fleet that configures everything through
    .env.

    Every failure here raises rather than dropping the entry, for the same reason
    `_d_role_models` does: a provider that silently vanishes from the registry turns
    every `provider::model` chain entry into an unknown-provider error at the first
    LLM call, hours after the config was written.

    `openrouter` is reserved — it is the implicit provider every bare `org/model`
    entry already resolves through, and letting a config point that name somewhere
    else would silently redirect the whole fleet.
    """
    if value is None or value == "" or value == {} or value == []:
        return ()
    triples: list[tuple[str, str, str]] = []
    if isinstance(value, str):
        for entry in (p.strip() for p in value.split(",")):
            if not entry:
                continue
            name, sep, rest = entry.partition("=")
            base_url, bar, api_key_env = rest.partition("|")
            if not sep or not bar or not name.strip() or not base_url.strip():
                raise ValueError(
                    f"providers entry must be 'name=base_url|API_KEY_ENV', got {entry!r} "
                    "(MY_CREW_PROVIDERS in .env)"
                )
            triples.append((name.strip(), base_url.strip(), api_key_env.strip()))
    elif isinstance(value, dict):
        for name, spec in value.items():
            if not isinstance(spec, dict):
                raise ValueError(
                    f"providers[{name!r}] must be a mapping with base_url and "
                    f"api_key_env, got {spec!r}"
                )
            base_url = spec.get("base_url")
            api_key_env = spec.get("api_key_env")
            if not isinstance(base_url, str) or not base_url.strip():
                raise ValueError(
                    f"providers[{name!r}].base_url must be a non-empty URL string, "
                    f"got {base_url!r}"
                )
            if not isinstance(api_key_env, str) or not api_key_env.strip():
                raise ValueError(
                    f"providers[{name!r}].api_key_env must name an environment "
                    f"variable, got {api_key_env!r} — put the env var NAME here, "
                    "never the key itself"
                )
            triples.append((str(name).strip(), base_url.strip(), api_key_env.strip()))
    else:
        raise ValueError(
            "providers must be a mapping or a 'name=base_url|API_KEY_ENV,...' string"
        )

    seen: set[str] = set()
    for name, base_url, api_key_env in triples:
        if name == "openrouter":
            raise ValueError(
                "provider name 'openrouter' is reserved — it is the implicit provider "
                "every bare 'org/model' entry already uses; pick another name"
            )
        if not _PROVIDER_NAME_RE.fullmatch(name):
            raise ValueError(
                f"provider name {name!r} must be lowercase letters, digits and hyphens "
                "— it is the prefix in 'name::model', so it cannot contain ':' or '/'"
            )
        if not base_url.startswith(("http://", "https://")):
            raise ValueError(
                f"providers[{name!r}].base_url must start with http:// or https://, "
                f"got {base_url!r}"
            )
        if name in seen:
            raise ValueError(f"providers declares {name!r} twice")
        seen.add(name)
        # An env var holding something that looks like a key rather than a NAME is the
        # one mistake that leaks a secret into yaml, so reject the shape outright.
        if not _ENV_NAME_RE.fullmatch(api_key_env):
            raise ValueError(
                f"providers[{name!r}].api_key_env must be an environment variable NAME "
                f"(A-Z, digits, underscore), got {api_key_env!r} — never the key value"
            )
    return tuple(triples)


def _d_trust_mode(value: Any) -> str:
    """Coerce/validate `trust_mode`. Absent/empty ⇒ "autonomous" (the product default).

    Only "autonomous" | "guarded" are meaningful policies; anything else must fail at
    config load, not silently behave as one of them at the gateway's interrupt branch.
    """
    if value is None or value == "":
        return "autonomous"
    mode = str(value).strip().lower()
    if mode not in ("autonomous", "guarded"):
        raise ValueError(
            f"trust_mode must be 'autonomous' or 'guarded', got {value!r} "
            "(safety.trust_mode in profile.yaml or TRUST_MODE in .env)"
        )
    return mode


def build_settings_from_dict(d: dict[str, Any]) -> Settings:
    """Build Settings from a plain dict. Pure: no env, no I/O. All keys optional."""
    data_dir = d.get("data_dir", DATA_DIR)
    return Settings(
        openrouter_api_key=_d_str_or_none(d, "openrouter_api_key"),
        openrouter_model=d.get("openrouter_model") or DEFAULT_MODEL,
        openrouter_referer=d.get("openrouter_referer")
        or "https://github.com/local/my-crew",
        openrouter_title=d.get("openrouter_title") or "my-crew",
        model_chain=_d_model_chain(d.get("model_chain")),
        role_models=_d_role_models(d.get("role_models")),
        providers=_d_providers(d.get("providers")),
        dry_run=_d_bool(d, "dry_run", True),
        write_disabled=_d_bool(d, "write_disabled", False),
        trust_mode=_d_trust_mode(d.get("trust_mode")),
        monthly_budget_usd=_d_float(d, "monthly_budget_usd", 50.0),
        budget_warn_ratio=_d_float(d, "budget_warn_ratio", 0.8),
        data_dir=Path(data_dir) if not isinstance(data_dir, Path) else data_dir,
        checkpointer=(d.get("checkpointer") or "sqlite").lower(),
        # v66: absent ⇒ "sqlite" (persistent shared memory store, CEO decision
        # 2026-08-04); an explicit "memory" keeps the old in-process behavior.
        store=(d.get("store") or "sqlite").lower(),
        postgres_dsn=_d_str_or_none(d, "postgres_dsn"),
        tracing=_d_bool(d, "tracing", False),
        tavily_api_key=_d_str_or_none(d, "tavily_api_key"),
        brave_api_key=_d_str_or_none(d, "brave_api_key"),
        firecrawl_base_url=_d_str_or_none(d, "firecrawl_base_url"),
        firecrawl_api_key=_d_str_or_none(d, "firecrawl_api_key"),
        step_transcripts=_d_bool(d, "step_transcripts", True),
        review_transcript_evidence_max_chars=_d_int(
            d, "review_transcript_evidence_max_chars", 8000
        ),
        step_activity_feed=_d_bool(d, "step_activity_feed", True),
        reflection_transcript_evidence_max_chars=_d_int(
            d, "reflection_transcript_evidence_max_chars", 4000
        ),
        advisor_enabled=_d_bool(d, "advisor_enabled", False),
    )


def build_settings_from_env() -> Settings:
    """Load .env + read os.environ into a dict, then delegate to from_dict.

    Reproduces the v1 env-loaded settings exactly (same keys, same coercion).
    """
    from my_crew.config.settings import MY_CREW_HOME
    from my_crew.runtime.run_config import tracing_env_on

    load_dotenv(MY_CREW_HOME / ".env")
    return build_settings_from_dict(
        {
            "openrouter_api_key": os.getenv("OPENROUTER_API_KEY"),
            "openrouter_model": os.getenv("OPENROUTER_MODEL"),
            "openrouter_referer": os.getenv("OPENROUTER_REFERER"),
            "openrouter_title": os.getenv("OPENROUTER_TITLE"),
            "model_chain": os.getenv("OPENROUTER_MODEL_CHAIN"),
            "role_models": os.getenv("OPENROUTER_ROLE_MODELS"),
            "providers": os.getenv("MY_CREW_PROVIDERS"),
            "dry_run": os.getenv("DRY_RUN"),
            "write_disabled": os.getenv("AGENT_WRITE_DISABLED"),
            "trust_mode": os.getenv("TRUST_MODE"),
            "monthly_budget_usd": os.getenv("MONTHLY_BUDGET_USD"),
            "budget_warn_ratio": os.getenv("BUDGET_WARN_RATIO"),
            "data_dir": DATA_DIR,
            "checkpointer": os.getenv("CHECKPOINTER_TYPE"),
            "store": os.getenv("STORE_TYPE"),
            "postgres_dsn": os.getenv("POSTGRES_DSN"),
            "tavily_api_key": os.getenv("TAVILY_API_KEY"),
            "brave_api_key": os.getenv("BRAVE_API_KEY"),
            "firecrawl_base_url": os.getenv("FIRECRAWL_BASE_URL"),
            "firecrawl_api_key": os.getenv("FIRECRAWL_API_KEY"),
            "step_transcripts": os.getenv("STEP_TRANSCRIPTS"),
            "review_transcript_evidence_max_chars": os.getenv(
                "REVIEW_TRANSCRIPT_EVIDENCE_MAX_CHARS"
            ),
            "step_activity_feed": os.getenv("STEP_ACTIVITY_FEED"),
            "reflection_transcript_evidence_max_chars": os.getenv(
                "REFLECTION_TRANSCRIPT_EVIDENCE_MAX_CHARS"
            ),
            "advisor_enabled": os.getenv("ADVISOR_ENABLED"),
            # Tracing is on (env side) when either the V2 flag is truthy OR an API key is
            # present — normalized to a bool so an API-key string (not a true/false word)
            # still enables. Shared helper so the worker/cli settings path and the server
            # env-only path agree on the same signal.
            "tracing": tracing_env_on(),
        }
    )
