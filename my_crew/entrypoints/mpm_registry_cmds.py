"""`mpm agent list` + `mpm agent register` — read the registry + scaffold a new agent.

`list` reads `registry.yaml` (id + enabled), each profile's `name`, and the last
`runs.jsonl` line for the agent's last-run. `register` scaffolds `profiles/<id>/` from
the committed `default` template and text-appends a `{id, enabled: true}` block to
`registry.yaml` (preserving the existing comments + entries). Both take optional
`registry_path` / `profiles_dir` kwargs so tests run against tmp paths and never touch
the real committed files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from my_crew.profile.loader import _PROFILES_DIR, load_profile
from my_crew.runtime.agent_paths import _validate_agent_id, agent_data_dir
from my_crew.runtime.registry import _REGISTRY_PATH, load_registry
from my_crew.runtime.registry_edit import append_registry, scaffold_profile_dir


def _last_run(data_dir: Path) -> str:
    """Format the agent's last run-event as `<kind> <status> @<ts>`, or 'never run'."""
    path = data_dir / "runs.jsonl"
    if not path.exists():
        return "never run"
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return "never run"
    try:
        ev = json.loads(lines[-1])
    except json.JSONDecodeError:
        return "never run"
    return f"{ev.get('kind', '?')} {ev.get('status', '?')} @{str(ev.get('ts', ''))[:19]}"


def run_list(
    args: list[str], *, registry_path: Path | None = None, profiles_dir: Path | None = None
) -> int:
    """`mpm agent list` — print id / name / enabled / last-run for every registry entry."""
    entries = load_registry(registry_path)
    if not entries:
        print("(no agents registered)")
        return 0
    for e in entries:
        try:
            name = load_profile(e.id, profiles_dir=profiles_dir).name
        except (FileNotFoundError, RuntimeError) as exc:
            name = f"<error: {exc}>"
        enabled = "enabled" if e.enabled else "disabled"
        print(f"{e.id:16}  {name:28}  {enabled:9}  {_last_run(agent_data_dir(e.id))}")
    return 0


def run_register(
    args: list[str], *, registry_path: Path | None = None, profiles_dir: Path | None = None
) -> int:
    """`mpm agent register <id>` — scaffold the profile + add it to the registry."""
    if not args:
        print("usage: mpm agent register <id>", file=sys.stderr)
        return 2
    agent_id = args[0]
    try:
        _validate_agent_id(agent_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    reg = registry_path if registry_path is not None else _REGISTRY_PATH
    pdir = profiles_dir if profiles_dir is not None else _PROFILES_DIR
    # Check BOTH collision targets before any write (no partial scaffold).
    if (pdir / agent_id).exists():
        print(f"error: profiles/{agent_id}/ already exists.", file=sys.stderr)
        return 1
    if any(e.id == agent_id for e in load_registry(reg)):
        print(f"error: {agent_id!r} is already in the registry.", file=sys.stderr)
        return 1

    scaffold_profile_dir(pdir, agent_id)
    append_registry(reg, agent_id)
    print(f"registered {agent_id}: profiles/{agent_id}/ + registry.yaml")
    return 0
