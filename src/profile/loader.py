"""Load a `profiles/<id>/` directory into a `LoadedProfile` (v2 M1-P2).

An agent = a directory of 4 concern-split files (profile-design.md §3):
  - `profile.yaml` (required): structured config → P1's `Settings` + `ReportingConfig`.
  - `SOUL.md` / `PROJECT.md` / `MEMORY.md` (optional): persona / project-context /
    agent-memory, read verbatim into strings ("" if absent).

The loader maps `profile.yaml` → the two P1 `from_dict` dicts (see `loader_mapping`),
calls the P1 builders (which own all validation, incl. the stakeholder-channel
guardrail), and reads the 3 Markdown files. `token_env`/server tokens resolve from
`os.environ` here; a MISSING token does NOT fail load — validation stays lazy at MCP
server spawn (`McpServerSpec.validate()`), matching v1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.config.config_builders import (
    build_reporting_config_from_dict,
    build_settings_from_dict,
)
from src.config.reporting_config import ReportingConfig
from src.config.settings import DATA_DIR, REPO_ROOT, Settings
from src.memory.provider import MemoryConfig, parse_memory_config
from src.profile.loader_mapping import build_reporting_dict, build_settings_dict

_PROFILES_DIR = REPO_ROOT / "profiles"


def profile_memory_path(profile_id: str, *, profiles_dir: Path | None = None) -> Path:
    """The agent's MEMORY.md path (where the M2-P8 `remember` node mirrors facts)."""
    base = profiles_dir if profiles_dir is not None else _PROFILES_DIR
    return base / profile_id / "MEMORY.md"


@dataclass(frozen=True)
class LoadedProfile:
    """One agent's resolved config + context. `settings`/`config` are P1 objects.

    `schedule`/`reports`/`enabled`/`name` are parsed + shape-validated but UNUSED in
    M1 — they are consumed in P3 (scheduler / kind-gate / registry).
    """

    profile_id: str
    name: str
    enabled: bool  # consumed in P3 (registry)
    settings: Settings
    config: ReportingConfig
    soul: str  # SOUL.md verbatim ("" if absent)
    project: str  # PROJECT.md verbatim
    memory: str  # MEMORY.md verbatim (A1 memory-injection, read-only in M1)
    schedule: dict[str, str]  # consumed in P3 (scheduler)
    reports: tuple[str, ...]  # consumed in P3 (kind gate)
    skills: tuple[str, ...] = ()  # M3-P10: per-agent skill candidate pool (names)
    company_docs: tuple[str, ...] = ()  # M19: opted-in company-doc slugs (internal-only inject)
    project_group: str | None = None  # M3-P9: sibling group slug (None ⇒ no siblings)
    domain: str = "pm"  # v3 M5: which domain pack drives this agent (absent ⇒ "pm")
    # v3 M11: ask-agent Slack inbox (opt-in). None ⇒ no polling, byte-identical pre-M11.
    # Shape: {"channel": "<slack channel ID>", "poll_minutes": int>=1}. INTERNAL channel
    # only in M11 — an external channel is rejected at load (see _parse_inbox).
    inbox: dict | None = None
    # v8 M23 trust ladder: auto-approve config. None ⇒ OFF (byte-identical pre-M23).
    # Shape: {"scheduled_reports": [kind...], "actions": {type: {enabled, max_per_day,
    # channels|recipients}}, "trusted_senders": {"telegram": [id...]}}. Validated at load.
    auto_approve: dict | None = None
    # Opt-in web-search flag for team-task steps. Default False ⇒ `search_hook`
    # resolves to None regardless of provider keys (see `team_step_runner.py`).
    web_search: bool = False
    # v19 memory seam: which provider serves the injectable memory text. Absent ⇒ static
    # (MEMORY.md, byte-identical pre-v19). Consumed by `src/memory.resolve_memory_text`.
    memory_config: MemoryConfig = field(default_factory=MemoryConfig)


def _read_md(profile_dir: Path, name: str) -> str:
    """Read an optional Markdown file verbatim; missing ⇒ empty string."""
    path = profile_dir / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def load_profile(
    profile_id: str, *, profiles_dir: Path | None = None, data_dir: Path | None = None
) -> LoadedProfile:
    """Load `profiles/<profile_id>/` into a LoadedProfile.

    `data_dir` (None ⇒ the global `DATA_DIR`, P2-identical) sets `settings.data_dir`,
    which every store keys off — pass `.data/agents/<id>/` (M1-P3) to isolate the agent.

    Raises FileNotFoundError if `profile.yaml` is missing (a typo'd `--profile` should
    fail loudly — distinct from an absent OPTIONAL `.md`). Raises RuntimeError from the
    P1 builders only on a real config error (e.g. stakeholder channel not in the
    external set). A missing token does NOT raise here (lazy, at spawn).
    """
    base = profiles_dir if profiles_dir is not None else _PROFILES_DIR
    profile_dir = base / profile_id
    yaml_path = profile_dir / "profile.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(
            f"Profile {profile_id!r} not found: {yaml_path} is missing. "
            f"Expected a directory profiles/{profile_id}/ with a profile.yaml."
        )

    # Load .env so the env-fallback (empty profile field → env) + token_env resolution
    # see the user's secrets, exactly as v1's build_*_from_env did. Existing os.environ
    # values win (load_dotenv does not override), so a caller-set env is respected.
    load_dotenv(REPO_ROOT / ".env")

    yaml_doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    if not isinstance(yaml_doc, dict):
        raise RuntimeError(
            f"profile.yaml for {profile_id!r} must be a mapping, got {type(yaml_doc).__name__}."
        )

    resolved_data_dir = data_dir if data_dir is not None else DATA_DIR
    settings = build_settings_from_dict(build_settings_dict(yaml_doc, resolved_data_dir))
    config = build_reporting_config_from_dict(build_reporting_dict(yaml_doc))

    schedule = yaml_doc.get("schedule") or {}
    reports = yaml_doc.get("reports") or []
    skills = yaml_doc.get("skills") or []
    company_docs = yaml_doc.get("company_docs") or []
    project_raw = yaml_doc.get("project")
    project_group = str(project_raw).strip() or None if project_raw is not None else None
    # A blank/absent `domain:` defaults to "pm" so every pre-v3 profile (which never
    # declared a domain) keeps loading as a PM agent — backward-compat is load-bearing.
    domain_raw = yaml_doc.get("domain")
    domain = str(domain_raw).strip() or "pm" if domain_raw is not None else "pm"
    schedule_map = (
        {str(k): str(v) for k, v in schedule.items()} if isinstance(schedule, dict) else {}
    )
    inbox = _parse_inbox(yaml_doc.get("inbox"), config)
    auto_approve = _parse_auto_approve(yaml_doc.get("auto_approve"))
    web_search = bool(yaml_doc.get("web_search", False))
    memory_config = parse_memory_config(yaml_doc.get("memory"))
    return LoadedProfile(
        profile_id=profile_id,
        name=str(yaml_doc.get("name") or profile_id),
        enabled=bool(yaml_doc.get("enabled", True)),
        settings=settings,
        config=config,
        soul=_read_md(profile_dir, "SOUL.md"),
        project=_read_md(profile_dir, "PROJECT.md"),
        memory=_read_md(profile_dir, "MEMORY.md"),
        schedule=schedule_map,
        reports=tuple(str(r) for r in reports) if isinstance(reports, list) else (),
        skills=tuple(str(s) for s in skills) if isinstance(skills, list) else (),
        company_docs=tuple(str(s) for s in company_docs) if isinstance(company_docs, list) else (),
        project_group=project_group,
        domain=domain,
        inbox=inbox,
        auto_approve=auto_approve,
        web_search=web_search,
        memory_config=memory_config,
    )


def _parse_auto_approve(raw: object) -> dict | None:
    """Validate the optional `auto_approve:` block (v8 M23). Absent/empty ⇒ None (OFF).

    Fail-loud on shape errors so a typo can't silently grant or silently disable trust. The
    known action-types are the ones the policy classifies (slack_post / email_send); an
    unknown type is rejected rather than silently ignored (a misfiled grant must not read as
    'off')."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise RuntimeError("auto_approve must be a mapping.")
    out: dict = {}
    sched = raw.get("scheduled_reports")
    if sched is not None:
        if not isinstance(sched, list):
            raise RuntimeError("auto_approve.scheduled_reports must be a list of report kinds.")
        out["scheduled_reports"] = [str(k) for k in sched]
    actions = raw.get("actions")
    if actions is not None:
        if not isinstance(actions, dict):
            raise RuntimeError("auto_approve.actions must be a mapping of action-type→grant.")
        known = {"slack_post", "email_send"}
        clean_actions: dict = {}
        for atype, grant in actions.items():
            if atype not in known:
                raise RuntimeError(f"auto_approve.actions: unknown action-type {atype!r} "
                                   f"(known: {sorted(known)}).")
            if not isinstance(grant, dict):
                raise RuntimeError(f"auto_approve.actions.{atype} must be a mapping.")
            mpd = grant.get("max_per_day", 0)
            if not isinstance(mpd, int) or isinstance(mpd, bool) or mpd < 0:
                raise RuntimeError(f"auto_approve.actions.{atype}.max_per_day must be int>=0.")
            g: dict = {"enabled": bool(grant.get("enabled", False)), "max_per_day": mpd}
            dests = grant.get("channels") if atype == "slack_post" else grant.get("recipients")
            if dests is not None:
                if not isinstance(dests, list):
                    raise RuntimeError(f"auto_approve.actions.{atype} destinations must be a list.")
                key = "channels" if atype == "slack_post" else "recipients"
                g[key] = [str(d) for d in dests]
            clean_actions[atype] = g
        out["actions"] = clean_actions
    trusted = raw.get("trusted_senders")
    if trusted is not None:
        if not isinstance(trusted, dict):
            raise RuntimeError("auto_approve.trusted_senders must be a mapping of transport→ids.")
        out["trusted_senders"] = {
            str(t): [str(i) for i in (ids or [])] for t, ids in trusted.items()
        }
    return out or None


def _parse_inbox(raw: object, config: ReportingConfig) -> dict | None:
    """Validate the optional `inbox:` block (v3 M11). Absent/empty ⇒ None.

    Fail-loud on shape errors, and REJECT an external channel: the QA reply prompt
    injects persona/memory (internal-only context per the audience red line), so M11
    supports internal channels only — answering stakeholders needs the external prompt
    split first (deferred, see phase-m11).
    """
    if raw is None or raw == {} or raw == "":
        return None
    if not isinstance(raw, dict):
        raise RuntimeError("profile inbox: must be a mapping {channel, poll_minutes}.")
    channel = str(raw.get("channel") or "").strip()
    if not channel:
        raise RuntimeError("profile inbox: needs a Slack channel id (channel:).")
    if channel in config.slack_external_channels:
        raise RuntimeError(
            f"profile inbox: channel {channel!r} is an EXTERNAL channel — the M11 ask-agent"
            " inbox is internal-only (persona/memory context must not reach stakeholders)."
        )
    try:
        poll = int(raw.get("poll_minutes", 5))
    except (TypeError, ValueError):
        raise RuntimeError("profile inbox: poll_minutes must be an integer >= 1.") from None
    if poll < 1:
        raise RuntimeError("profile inbox: poll_minutes must be an integer >= 1.")
    return {"channel": channel, "poll_minutes": poll}
