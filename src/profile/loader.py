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
from src.runtime_backends.config import AgentRuntimeConfig, parse_agent_runtime_config

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
    # v31 P6: opt-in OpenAlex academic search for tool-calling runtimes. Default False ⇒
    # the `academic.search` tool is not offered (toolset byte-identical). OpenAlex needs
    # no key, so this flag IS the gate (there is no config-availability gate to lean on).
    academic_search: bool = False
    # v39 #1: opt-in Google Workspace READ tools (Gmail/Calendar/Drive) for tool-calling
    # runtimes. Default False ⇒ the gws.* tools are not offered (toolset byte-identical).
    # The gws CLI's OAuth is the credential; no key gate to lean on, so the flag IS the gate.
    gws_context: bool = False
    # v43: opt-in in-sandbox subagent delegation for a deep_agent team-step. Default False ⇒ no
    # curated `general-purpose` subagent spec is passed to create_deep_agent and no delegation-cap
    # middleware is attached (byte-identical to today; the deepagents-default subagent, if it fires,
    # is unchanged). When True, run_deep_agent_work wires a compose-early subagent + a hard cap on
    # the number of `task` delegations. deep_agent tier only (others have no sandbox/subagents).
    deep_team: bool = False
    # v44: optional per-agent override of the deep_team delegation cap (default _MAX_TASK_CALLS=3,
    # clamped in the loop). None ⇒ default. Kept as a SEPARATE int (not a bool→int widening of
    # deep_team) so the ON/OFF gate stays a clean bool and `int 0` can't accidentally read as off.
    deep_team_max_calls: int | None = None
    # v19 memory seam: which provider serves the injectable memory text. Absent ⇒ static
    # (MEMORY.md, byte-identical pre-v19). Consumed by `src/memory.resolve_memory_text`.
    memory_config: MemoryConfig = field(default_factory=MemoryConfig)
    # v20 agent-runtime seam: which loop backend runs this agent. Absent ⇒ native (existing
    # graphs, byte-identical). TOP-LEVEL `agent_runtime:` key, NOT the infra `runtime:` block.
    agent_runtime: AgentRuntimeConfig = field(default_factory=AgentRuntimeConfig)
    # v20.5 Phase 0: opt-in team-step external egress. None ⇒ team-step writes only the internal
    # artifact (byte-identical pre-v20.5). Shape: {"channel": "<slack channel id>"} — when set,
    # a step's result is posted to that channel THROUGH the Action Gateway (Lớp A/B + audit).
    team_step_egress: dict | None = None
    # v31 P5 wake-gate: declared source watchers. () ⇒ no `watch` pseudo-kind is ever
    # synthesized (schedule byte-identical). Each entry: {id, source, target, prompt} —
    # validated at load by `_parse_watchers`.
    watchers: tuple[dict, ...] = ()
    # v36 P2 template live-skills: the role template this agent was created from. None ⇒
    # agent predates live-skills (its skills were COPIED into profiles/<id>/skills/ once at
    # create — byte-identical old behavior). When set, `load_skill_pool` ALSO loads the
    # template's skills/ dir live at runtime, so a template skill edit reaches every agent
    # of that role without re-scaffolding.
    template_role: str | None = None


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
    team_step_egress = _parse_team_step_egress(yaml_doc.get("team_step_egress"))
    auto_approve = _parse_auto_approve(yaml_doc.get("auto_approve"))
    web_search = bool(yaml_doc.get("web_search", False))
    academic_search = bool(yaml_doc.get("academic_search", False))
    gws_context = bool(yaml_doc.get("gws_context", False))
    deep_team = bool(yaml_doc.get("deep_team", False))
    deep_team_max_calls = _parse_deep_team_max_calls(yaml_doc.get("deep_team_max_calls"))
    memory_config = parse_memory_config(yaml_doc.get("memory"))
    agent_runtime = parse_agent_runtime_config(yaml_doc.get("agent_runtime"))
    watchers = _parse_watchers(yaml_doc.get("watchers"))
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
        academic_search=academic_search,
        gws_context=gws_context,
        deep_team=deep_team,
        deep_team_max_calls=deep_team_max_calls,
        memory_config=memory_config,
        agent_runtime=agent_runtime,
        team_step_egress=team_step_egress,
        watchers=watchers,
        template_role=(str(yaml_doc.get("template_role") or "").strip() or None),
    )


#: Sources `watchers:` may declare. confluence/linear parse but FAIL-CLOSED at poll
#: time (watcher_normalize) — declaring them is allowed so the operator sees a loud
#: per-watcher error + alert instead of a load crash taking the whole agent down.
_WATCHER_SOURCES = frozenset({"jira", "github", "sheets", "confluence", "linear"})


def _parse_watchers(raw: object) -> tuple[dict, ...]:
    """Validate the optional `watchers:` block (v31 P5). Absent/empty ⇒ () (no watch).

    Fail-loud on shape errors: a typo'd watcher silently dropped would read as "the
    agent is watching" while nothing polls. Each entry needs a unique non-empty `id`,
    a known `source`, a non-empty `target`, and a non-empty agent-owned `prompt`
    (the ONLY text a wake ever carries — watched content never enters a prompt).
    """
    if raw is None or raw == []:
        return ()
    if not isinstance(raw, list):
        raise RuntimeError("watchers: must be a list of {id, source, target, prompt}.")
    out: list[dict] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise RuntimeError(f"watchers: each entry must be a mapping; got {entry!r}.")
        wid = str(entry.get("id") or "").strip()
        source = str(entry.get("source") or "").strip().lower()
        target = str(entry.get("target") or "").strip()
        prompt = str(entry.get("prompt") or "").strip()
        if not wid or wid in seen:
            raise RuntimeError(f"watchers: 'id' must be non-empty and unique; got {wid!r}.")
        if source not in _WATCHER_SOURCES:
            raise RuntimeError(
                f"watchers: source {source!r} không hợp lệ (biết: "
                f"{', '.join(sorted(_WATCHER_SOURCES))})."
            )
        if not target:
            raise RuntimeError(f"watchers {wid!r}: 'target' must be non-empty.")
        if not prompt:
            raise RuntimeError(f"watchers {wid!r}: 'prompt' must be non-empty.")
        seen.add(wid)
        out.append({"id": wid, "source": source, "target": target, "prompt": prompt})
    return tuple(out)


def _parse_deep_team_max_calls(raw: object) -> int | None:
    """Validate the optional `deep_team_max_calls:` (v44). Absent ⇒ None (default cap in the loop).

    Fail LOUD on a bad type — matching the loader's posture for other typed numeric fields
    (auto_approve.max_per_day) — so a quoted "5" or a `true` typo surfaces to the operator instead
    of silently reverting to the default. `bool` is rejected explicitly (it is an int subclass)."""
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise RuntimeError("deep_team_max_calls must be an int (clamped to [1,8] at runtime).")
    return raw


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


def _parse_team_step_egress(raw: object) -> dict | None:
    """Validate the optional `team_step_egress:` block (v20.5 Phase 0). Absent/empty ⇒ None.

    None means a team-step writes only its internal artifact (byte-identical pre-v20.5). When
    set, a step's result posts to `channel` THROUGH the gateway. Fail-loud on shape errors.
    """
    if raw is None or raw == {} or raw == "":
        return None
    if not isinstance(raw, dict):
        raise RuntimeError("profile team_step_egress: must be a mapping {channel: ...}.")
    channel = str(raw.get("channel") or "").strip()
    if not channel:
        raise RuntimeError("profile team_step_egress: needs a Slack channel id (channel:).")
    return {"channel": channel}
