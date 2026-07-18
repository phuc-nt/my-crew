"""Agent registry — the list of agents the coordinating service runs (v2 M1-P3).

`registry.yaml` (repo root) holds only agent ids + an enabled flag — no secrets — so
the service knows which `profiles/<id>/` to load. An agent runs only when BOTH its
registry `enabled` AND its profile's `enabled` are true (registry is the master
switch; the profile is the secondary gate).

v18: the file is USER DATA (gitignored, like company.yaml/profiles) — the CEO's real
team must never be reverted by a git operation. `registry.example.yaml` is the
committed template; `load_registry` bootstraps the real file from it on first run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from my_crew.config.settings import REPO_ROOT
from my_crew.runtime.agent_paths import _validate_agent_id

_REGISTRY_PATH = REPO_ROOT / "registry.yaml"

#: Committed template a fresh checkout bootstraps `registry.yaml` from (v18 — the real
#: registry is user data and no longer lives in git).
_EXAMPLE_PATH = REPO_ROOT / "registry.example.yaml"


@dataclass(frozen=True)
class RegistryEntry:
    """One agent in the registry: its id + the master enabled switch."""

    id: str
    enabled: bool


def load_registry(path: Path | None = None) -> tuple[RegistryEntry, ...]:
    """Load + shape-validate `registry.yaml` into a tuple of entries.

    Raises FileNotFoundError if the file is missing, RuntimeError on a malformed file
    (no `agents` list, an entry without a non-empty `id`, or a duplicate id). `enabled`
    defaults to True when omitted.
    """
    registry_path = path if path is not None else _REGISTRY_PATH
    # v18 bootstrap — DEFAULT path only: a fresh checkout has no registry.yaml (user
    # data), so mint one from the committed example. Callers passing an explicit
    # `path` (tests, registry_edit's validate-on-tmp, --registry) keep the strict
    # FileNotFoundError contract.
    if path is None and not registry_path.exists() and _EXAMPLE_PATH.exists():
        import os
        import shutil

        tmp = registry_path.with_suffix(f".bootstrap.{os.getpid()}.tmp")
        shutil.copyfile(_EXAMPLE_PATH, tmp)
        os.replace(tmp, registry_path)  # atomic — two racing boots both end up whole
        import logging

        logging.getLogger(__name__).info("registry.yaml bootstrapped from example")
    if not registry_path.exists():
        raise FileNotFoundError(f"Registry not found: {registry_path} is missing.")

    doc = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    agents = doc.get("agents") if isinstance(doc, dict) else None
    if not isinstance(agents, list):
        raise RuntimeError(f"{registry_path}: 'agents' must be a list of {{id, enabled}}.")

    entries: list[RegistryEntry] = []
    seen: set[str] = set()
    for raw in agents:
        if not isinstance(raw, dict):
            raise RuntimeError(f"{registry_path}: each agent must be a mapping; got {raw!r}.")
        raw_id = raw.get("id")
        # An id must be a real string. YAML 1.1 turns bare `on`/`off`/`yes`/`no`/`true`
        # into a bool — quote it (`id: "on"`) to use it as an id, else it would silently
        # route to the wrong agent dir.
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise RuntimeError(
                f"{registry_path}: agent 'id' must be a non-empty string; got {raw_id!r}. "
                "If it is a YAML reserved word (on/off/yes/no/true/false), quote it."
            )
        agent_id = raw_id.strip()
        # Enforce the agent-id safety rule HERE so the id is validated once, at the
        # registry boundary — every downstream use (data dir, thread id, worker argv)
        # then trusts it. A bad id can't reach a Popen argv or a data path.
        try:
            _validate_agent_id(agent_id)
        except ValueError as exc:
            raise RuntimeError(f"{registry_path}: {exc}") from exc
        if agent_id in seen:
            raise RuntimeError(f"{registry_path}: duplicate agent id {agent_id!r}.")
        seen.add(agent_id)
        entries.append(RegistryEntry(id=agent_id, enabled=bool(raw.get("enabled", True))))
    return tuple(entries)
