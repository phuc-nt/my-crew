"""Map a parsed `profile.yaml` (+ os.environ) into the two P1 `from_dict` dicts.

The loader builds two plain dicts whose keys are EXACTLY the keys
`build_settings_from_dict` / `build_reporting_config_from_dict` consume
(`src/config/config_builders.py`, `config_builders_reporting.py`). No new config
validation lives here — P1's `from_dict` owns it.

Resolution is a three-tier rule per field (see plan §"The env-fallback rule"):

    profile.yaml value (set & non-empty)  →  else env var  →  else omit (P1 default)

A missing key OR an empty/blank YAML scalar (`""`, `~`, null, `[]`) is treated as
UNSET and falls through to the env var the v1 `from_env` reads — so the committed
`default` template (deployment fields empty) DEFERS to the user's `.env` rather than
clobbering it, keeping `default` == v1.

NUMERIC thresholds where `0` is a valid value are passed via `_explicit` (the YAML
value wins as long as the key is present), so a real `0` is never mistaken for unset.
"""

from __future__ import annotations

import os
from typing import Any

# Fixed v1 env-var names for the server-env block — NOT per-agent in M1 (see plan
# token note: Atlassian = one shared token; Slack reads the two fixed names directly).
_FIXED_SERVER_ENV = {
    "atlassian_site_name": "ATLASSIAN_SITE_NAME",
    "atlassian_user_email": "ATLASSIAN_USER_EMAIL",
    "slack_xoxc_token": "SLACK_XOXC_TOKEN",
    "slack_xoxd_token": "SLACK_XOXD_TOKEN",
    "slack_team_domain": "SLACK_TEAM_DOMAIN",
}


def _fallback(yaml_value: Any, env_name: str | None) -> Any:
    """Three-tier resolve for STRING/LIST fields: yaml (if truthy) → env → None (omit).

    Returns None when both tiers are empty so the caller omits the key and P1's
    from_dict applies the v1 default. Never use this for a numeric field where `0`
    is valid — use `_explicit` instead.
    """
    if yaml_value:  # non-empty str / non-empty list / truthy scalar
        return yaml_value
    if env_name:
        env_value = os.environ.get(env_name)
        if env_value:
            return env_value
    return None


def _put(d: dict[str, Any], key: str, value: Any) -> None:
    """Set the dict key only when the value is not None (None ⇒ defer to from_dict)."""
    if value is not None:
        d[key] = value


def _section(yaml_doc: dict[str, Any], *path: str) -> dict[str, Any]:
    """Walk a nested mapping path, returning {} for any missing/non-mapping level."""
    node: Any = yaml_doc
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            return {}
    return node


def build_settings_dict(yaml_doc: dict[str, Any], data_dir: Any) -> dict[str, Any]:
    """profile.yaml → the dict `build_settings_from_dict` consumes."""
    budget = _section(yaml_doc, "budget")
    safety = _section(yaml_doc, "safety")
    runtime = _section(yaml_doc, "runtime")  # M2-P8 infra (checkpointer / store / dsn)
    out: dict[str, Any] = {"data_dir": data_dir}

    # API key is never in profile.yaml — read the fixed env name (same as v1).
    _put(out, "openrouter_api_key", os.environ.get("OPENROUTER_API_KEY"))
    _put(out, "openrouter_model", _fallback(yaml_doc.get("model"), "OPENROUTER_MODEL"))
    _put(out, "openrouter_referer", _fallback(None, "OPENROUTER_REFERER"))
    _put(out, "openrouter_title", _fallback(None, "OPENROUTER_TITLE"))
    # v4 M9: fallback chain — yaml list wins; else env comma string; else omit (⇒ single
    # model, byte-identical pre-v4). Coercion/validation lives in _d_model_chain.
    _put(out, "model_chain", _fallback(yaml_doc.get("model_chain"), "OPENROUTER_MODEL_CHAIN"))

    # Booleans: a present YAML key wins (incl. an explicit `false`); else env; else omit.
    _put(out, "dry_run", _explicit_bool(safety, "dry_run", "DRY_RUN"))
    _put(out, "write_disabled", _explicit_bool(safety, "write_disabled", "AGENT_WRITE_DISABLED"))

    _put(out, "monthly_budget_usd", _explicit(budget, "monthly_usd", "MONTHLY_BUDGET_USD"))
    _put(out, "budget_warn_ratio", _explicit(budget, "warn_ratio", "BUDGET_WARN_RATIO"))

    # M2-P8 runtime infra: yaml value → env → omit (build_settings_from_dict defaults
    # sqlite/memory/None). Empty yaml scalar defers to env, then the default.
    _put(out, "checkpointer", _fallback(runtime.get("checkpointer"), "CHECKPOINTER_TYPE"))
    _put(out, "store", _fallback(runtime.get("store"), "STORE_TYPE"))
    _put(out, "postgres_dsn", _fallback(runtime.get("postgres_dsn"), "POSTGRES_DSN"))
    # M3-P12 (B4): opt-in tracing flag (present yaml bool wins; else env). Default OFF.
    _put(out, "tracing", _explicit_bool(runtime, "tracing", "LANGCHAIN_TRACING_V2"))
    return out


def build_reporting_dict(yaml_doc: dict[str, Any]) -> dict[str, Any]:
    """profile.yaml → the dict `build_reporting_config_from_dict` consumes."""
    jira = _section(yaml_doc, "bindings", "jira")
    github = _section(yaml_doc, "bindings", "github")
    slack = _section(yaml_doc, "bindings", "slack")
    confluence = _section(yaml_doc, "bindings", "confluence")
    thresholds = _section(yaml_doc, "thresholds")
    out: dict[str, Any] = {}

    # --- Deployment STRINGS/LISTS: empty yaml scalar defers to env (then from_dict). ---
    _put(out, "jira_project_key", _fallback(jira.get("project_key"), "JIRA_PROJECT_KEY"))
    _put(out, "github_repo", _fallback(github.get("repo"), "GITHUB_REPO"))
    _put(
        out, "slack_report_channel", _fallback(slack.get("report_channel"), "SLACK_REPORT_CHANNEL")
    )
    _put(
        out,
        "slack_external_channels",
        _fallback(slack.get("external_channels"), "SLACK_EXTERNAL_CHANNELS"),
    )
    _put(
        out,
        "slack_stakeholder_channel",
        _fallback(slack.get("stakeholder_channel"), "SLACK_STAKEHOLDER_CHANNEL"),
    )
    _put(
        out, "confluence_space_key", _fallback(confluence.get("space_key"), "CONFLUENCE_SPACE_KEY")
    )
    _put(
        out, "confluence_space_id", _fallback(confluence.get("space_id"), "CONFLUENCE_SPACE_ID")
    )
    _put(
        out,
        "okr_confluence_page_id",
        _fallback(confluence.get("okr_page_id"), "OKR_CONFLUENCE_PAGE_ID"),
    )

    # --- dist overrides: yaml mcp_dist wins, else env, else from_dict default path. ---
    _put(out, "jira_mcp_dist", _fallback(jira.get("mcp_dist"), "JIRA_MCP_DIST"))
    _put(out, "slack_mcp_dist", _fallback(slack.get("mcp_dist"), "SLACK_MCP_DIST"))
    _put(out, "confluence_mcp_dist", _fallback(confluence.get("mcp_dist"), "CONFLUENCE_MCP_DIST"))

    # --- Thresholds: numeric, `0` is valid → explicit (present yaml key wins). ---
    _put(out, "pr_stale_days", _explicit(thresholds, "pr_stale_days", "PR_STALE_DAYS"))
    _put(
        out,
        "blocker_label_substring",
        _fallback(thresholds.get("blocker_label_substring"), "BLOCKER_LABEL_SUBSTRING"),
    )
    _put(
        out,
        "okr_behind_threshold",
        _explicit(thresholds, "okr_behind_threshold", "OKR_BEHIND_THRESHOLD"),
    )
    _put(
        out,
        "resource_overload_ratio",
        _explicit(thresholds, "resource_overload_ratio", "RESOURCE_OVERLOAD_RATIO"),
    )
    _put(
        out,
        "labor_cost_per_issue",
        _explicit(thresholds, "labor_cost_per_issue", "LABOR_COST_PER_ISSUE"),
    )

    # --- Server-env: Atlassian = one shared token (jira authoritative); fixed names. ---
    _put(out, "atlassian_api_token", _resolve_atlassian_token(jira, confluence))
    for dict_key, env_name in _FIXED_SERVER_ENV.items():
        _put(out, dict_key, os.environ.get(env_name))

    # --- M3-P11 (C3): config-driven extra MCP servers from the `integrations:` block. ---
    _put(out, "extra_servers", _build_integrations(yaml_doc))
    # --- M3-P11 (D2): outbound email channel from the `smtp:` block (password env-only). ---
    _put(out, "smtp", _build_smtp_mapping(yaml_doc))
    return out


def _build_integrations(yaml_doc: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Normalize the `integrations:` block → the `extra_servers` list from_dict consumes.

    Each entry: {name, mcp_dist, required_env}. `mcp_dist` resolves yaml → `<NAME>_MCP_DIST`
    env (so a profile can name the server but defer the path to env). `required_env` lists
    the env var NAMES the server reads — values are pulled from os.environ by from_dict, never
    stored in yaml. Returns None when no integrations declared (omit ⇒ extra_servers={}).
    """
    integrations = _section(yaml_doc, "integrations")
    if not integrations:
        return None
    out: list[dict[str, Any]] = []
    for raw_name, cfg in integrations.items():
        if not isinstance(cfg, dict):
            continue
        name = str(raw_name).strip().lower()
        dist = _fallback(cfg.get("mcp_dist"), f"{name.upper()}_MCP_DIST")
        required_env = [str(k) for k in (cfg.get("required_env") or [])]
        out.append({"name": name, "mcp_dist": dist or "", "required_env": required_env})
    return out or None


def _build_smtp_mapping(yaml_doc: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize the `smtp:` block → the dict `_build_smtp` consumes. None when absent.

    Each field resolves yaml → env (`SMTP_HOST`/`SMTP_PORT`/...). The PASSWORD is never
    mapped here — it is read from `SMTP_PASSWORD` at send time. A block with no host ⇒ None
    ⇒ no email channel (backward-compat).
    """
    smtp = _section(yaml_doc, "smtp")
    host = _fallback(smtp.get("host"), "SMTP_HOST")
    if not host:
        return None
    return {
        "host": host,
        "port": _fallback(smtp.get("port"), "SMTP_PORT"),
        "user": _fallback(smtp.get("user"), "SMTP_USER"),
        "from_addr": _fallback(smtp.get("from_addr"), "SMTP_FROM_ADDR"),
        "use_tls": _explicit_bool(smtp, "use_tls", "SMTP_USE_TLS"),
        "recipients": _fallback(smtp.get("recipients"), "SMTP_RECIPIENTS"),
    }


def _explicit(section: dict[str, Any], yaml_key: str, env_name: str) -> Any:
    """For numeric fields where `0` is valid: a PRESENT yaml key wins (even `0`/`False`);
    else env var; else None (omit ⇒ from_dict default)."""
    if yaml_key in section and section[yaml_key] is not None:
        return section[yaml_key]
    return os.environ.get(env_name) or None


def _explicit_bool(section: dict[str, Any], yaml_key: str, env_name: str) -> Any:
    """Boolean variant: a present yaml bool wins (incl. explicit `false`); else env.

    A SET-but-empty env var (`DRY_RUN=`) is passed through as `""` so P1's `_d_bool`
    coerces it to False — exactly as v1's `from_env` does. Only a genuinely ABSENT
    env var (None) is omitted, deferring to the from_dict default. (Distinguishing
    unset from set-empty is why this is not the `_explicit` `... or None` form.)
    """
    if yaml_key in section and section[yaml_key] is not None:
        return section[yaml_key]
    return os.environ.get(env_name)  # None if unset (omit); "" if set-empty (→ False)


def _resolve_atlassian_token(jira: dict[str, Any], confluence: dict[str, Any]) -> str | None:
    """Resolve the shared Atlassian token from `bindings.jira.token_env` (authoritative).

    Confluence reuses the same Atlassian credential (P1 `_build_servers`). If a profile
    names a DIFFERENT confluence token_env, prefer jira's and warn once (a P3 multi-agent
    concern). Missing env ⇒ "" so load succeeds and validate() raises at spawn (v1).
    """
    jira_token_env = jira.get("token_env")
    conf_token_env = confluence.get("token_env")
    if jira_token_env and conf_token_env and conf_token_env != jira_token_env:
        import warnings

        warnings.warn(
            f"Profile sets different token_env for jira ({jira_token_env!r}) and confluence "
            f"({conf_token_env!r}); using jira's (Atlassian uses one shared token in M1).",
            stacklevel=2,
        )
    if not jira_token_env:
        return None  # no token_env named → defer (server env gets "" via from_dict)
    return os.environ.get(jira_token_env, "")
