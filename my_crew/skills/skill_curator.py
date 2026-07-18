"""Skill curator (v38 #2) — usage-tracking + auto-archive of unused agent skills.

The loader/selector pick skills, but nothing tracked which skills an agent actually uses,
so a growing per-agent skill library rots (dead skills add noise to every selection). This
adds two pieces, both pure internal state (no gateway, no egress — invariant (d)):

- **Usage counter**: `record_usage` bumps a per-agent sidecar (`skill_usage.json`) each
  time a skill is chosen. Best-effort — a write failure never breaks selection.
- **Auto-archive sweep**: `run_skill_archive_sweep` moves an agent-OWN skill whose last
  use is older than `ARCHIVE_UNUSED_DAYS` (or that was never used since it appeared, past
  a grace window) into `profiles/<id>/skills/.archive/`. It NEVER deletes (recover by hand,
  like MEMORY.archive.md) and NEVER touches template-role skills (those live under
  `profiles/templates/`, are shared repo data, and load live per v36 — not the agent's to
  archive). Runs in the service hygiene block, out of the request path.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

#: An agent-own skill unused for this long is archived. Measured 2026-07-13: agent-own skill
#: dirs are currently empty (v36 live-load), so this is a forward-looking guard. Generous on
#: purpose — a skill is condensed-away only when clearly stale, and archive is reversible.
ARCHIVE_UNUSED_DAYS = 90

#: A skill file that has NEVER been used is archived only after existing at least this long,
#: so a freshly-added skill isn't swept before the agent has had a chance to use it.
NEVER_USED_GRACE_DAYS = 30

#: Min hours between archive sweeps for one agent. The service ticks every 60s and the
#: nightly hour-gate lets ~60 calls through the sweep window; this cooldown (mirroring
#: memory-consolidation's) makes all but the first a cheap no-op instead of re-globbing.
ARCHIVE_COOLDOWN_HOURS = 24

_USAGE_FILENAME = "skill_usage.json"
_ARCHIVE_STATE_FILENAME = "skill_archive_state.json"


def _usage_path(agent_id: str) -> Path:
    from my_crew.runtime.agent_paths import agent_data_dir

    return agent_data_dir(agent_id) / _USAGE_FILENAME


def _load_usage(agent_id: str) -> dict:
    try:
        return json.loads(_usage_path(agent_id).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def record_usage(agent_id: str, chosen_names, *, now: datetime | None = None) -> None:
    """Bump the usage counter + last_used for each chosen skill. Best-effort: any failure
    is logged and swallowed so it can never break the hot-path selection that calls it."""
    names = [n for n in (chosen_names or []) if n]
    if not names:
        return
    now = now or datetime.now()  # noqa: DTZ005 — local, matches the scheduler clock
    try:
        usage = _load_usage(agent_id)
        stamp = now.isoformat()
        for name in names:
            entry = usage.get(name) or {"count": 0}
            entry["count"] = int(entry.get("count", 0)) + 1
            entry["last_used"] = stamp
            usage[name] = entry
        path = _usage_path(agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(usage, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001 — telemetry write must never break selection
        logger.warning("skill usage record failed for %s (ignored)", agent_id, exc_info=True)


def _archive_reason(skill_file: Path, usage: dict, now: datetime) -> str | None:
    """Why this agent-own skill should be archived, or None to keep it."""
    entry = usage.get(skill_file.stem)
    if entry and entry.get("last_used"):
        try:
            last = datetime.fromisoformat(entry["last_used"])
        except ValueError:
            return None
        if _older_than(now, last, ARCHIVE_UNUSED_DAYS):
            return f"không dùng {ARCHIVE_UNUSED_DAYS}+ ngày"
        return None
    # Never used: archive only if the file is older than the grace window.
    try:
        mtime = datetime.fromtimestamp(skill_file.stat().st_mtime)  # noqa: DTZ006 — local mtime
    except OSError:
        return None
    if _older_than(now, mtime, NEVER_USED_GRACE_DAYS):
        return f"chưa từng dùng sau {NEVER_USED_GRACE_DAYS}+ ngày"
    return None


def _older_than(now: datetime, then: datetime, days: int) -> bool:
    try:
        return (now - then) > timedelta(days=days)
    except TypeError:  # naive/aware mix
        return (now.replace(tzinfo=None) - then.replace(tzinfo=None)) > timedelta(days=days)


def archive_agent_skills(agent_id: str, *, now: datetime | None = None,
                         profiles_dir: Path | None = None) -> list[str]:
    """Move this agent's stale OWN skills into `skills/.archive/`. Returns archived names.

    Only `profiles/<id>/skills/*.md` (agent-own) is scanned — template-role skills are not
    the agent's files and are skipped by construction (they live under templates/). Never
    deletes; a name collision in .archive/ is suffixed so no prior archive is overwritten.
    """
    from my_crew.packs.registry import profile_skills_dir

    now = now or datetime.now()  # noqa: DTZ005 — local, matches scheduler
    skills_dir = profile_skills_dir(agent_id, profiles_dir=profiles_dir)
    if not skills_dir.is_dir():
        return []
    usage = _load_usage(agent_id)
    archive_dir = skills_dir / ".archive"
    archived: list[str] = []
    for skill_file in sorted(skills_dir.glob("*.md")):
        reason = _archive_reason(skill_file, usage, now)
        if reason is None:
            continue
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = archive_dir / skill_file.name
        if target.exists():
            target = archive_dir / f"{skill_file.stem}.{int(skill_file.stat().st_mtime)}.md"
        skill_file.rename(target)
        archived.append(skill_file.stem)
        logger.info("skill-curator[%s]: archived %r (%s)", agent_id, skill_file.stem, reason)
    return archived


def _archive_state_path(agent_id: str) -> Path:
    from my_crew.runtime.agent_paths import agent_data_dir

    return agent_data_dir(agent_id) / _ARCHIVE_STATE_FILENAME


def _cooldown_active(agent_id: str, now: datetime) -> bool:
    """True if this agent was swept within ARCHIVE_COOLDOWN_HOURS (skip re-sweep)."""
    try:
        stamp = json.loads(_archive_state_path(agent_id).read_text(encoding="utf-8"))
        last = datetime.fromisoformat(stamp.get("last_sweep", ""))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    try:
        delta = now - last
    except TypeError:  # naive/aware mix
        delta = now.replace(tzinfo=None) - last.replace(tzinfo=None)
    return delta < timedelta(hours=ARCHIVE_COOLDOWN_HOURS)


def _stamp_archive_sweep(agent_id: str, now: datetime) -> None:
    path = _archive_state_path(agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_sweep": now.isoformat()}), encoding="utf-8")


def run_skill_archive_sweep(*, now: datetime | None = None) -> int:
    """Best-effort sweep over enabled agents; returns total skills archived. One broken
    agent never blocks the rest. A per-agent 24h cooldown makes the repeated hour-gated
    calls within one nightly window cheap no-ops (mirrors memory-consolidation)."""
    from my_crew.runtime.registry import load_registry

    now = now or datetime.now()  # noqa: DTZ005 — local, matches scheduler
    total = 0
    for entry in load_registry():
        if not getattr(entry, "enabled", False):
            continue
        try:
            if _cooldown_active(entry.id, now):
                continue
            _stamp_archive_sweep(entry.id, now)
            total += len(archive_agent_skills(entry.id, now=now))
        except Exception:  # noqa: BLE001 — per-agent isolation
            logger.warning("skill-curator: sweep failed for %s (ignored)",
                           getattr(entry, "id", "?"), exc_info=True)
    return total
