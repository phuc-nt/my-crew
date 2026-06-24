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

from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.config.config_builders import (
    build_reporting_config_from_dict,
    build_settings_from_dict,
)
from src.config.reporting_config import ReportingConfig
from src.config.settings import DATA_DIR, REPO_ROOT, Settings
from src.profile.loader_mapping import build_reporting_dict, build_settings_dict

_PROFILES_DIR = REPO_ROOT / "profiles"


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
    schedule_map = (
        {str(k): str(v) for k, v in schedule.items()} if isinstance(schedule, dict) else {}
    )
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
    )
