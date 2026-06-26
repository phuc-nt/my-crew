"""Cross-agent (sibling) memory read for the report compose prompt (v2 M3-P9 A3).

Two agents that share a `project:` group are siblings. An agent READS a sibling's
remembered facts (the same facts the A2 `remember` node wrote to the Store under
`(sibling_id, "memory")`) — read-only; it never writes a sibling's namespace. Those
facts feed an injectable selector (S2) and inject into the INTERNAL compose prompt only
(never external — the P5 red line, same gate as persona/project/memory/skills).

This is the single shared helper the 3 graph-build entry points call (S3). It mirrors
`skill_pool.build_skill_context`: the no-op path (no group / no siblings / no facts)
returns without constructing an `LlmClient` (allocation-free, key-free).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.agent.memory_node import _NAMESPACE_KIND  # single source of the "memory" namespace
from src.profile.loader import load_profile

if TYPE_CHECKING:
    from pathlib import Path

    from langgraph.store.base import BaseStore

    from src.config.settings import Settings
    from src.profile.loader import LoadedProfile
    from src.runtime.registry import RegistryEntry

logger = logging.getLogger(__name__)

#: Read-side hard cap on sibling facts injected — bounds the prompt even if the selector
#: (S2) passes everything. Separate from the selector's relevance filtering.
MAX_SIBLING_FACTS: int = 40


def enumerate_siblings(
    self_id: str,
    self_group: str | None,
    registry: tuple[RegistryEntry, ...],
    *,
    profiles_dir: Path | None = None,
    data_dir: Path | None = None,
) -> list[str]:
    """Return the ids of enabled registry agents in the same `project_group` (self excluded).

    No group ⇒ no siblings. A sibling whose profile fails to load is warned and SKIPPED
    (a broken sibling must never crash the reader's run). Deterministic registry order.
    """
    if self_group is None:
        return []
    siblings: list[str] = []
    for entry in registry:
        if not entry.enabled or entry.id == self_id:
            continue
        try:
            other = load_profile(entry.id, profiles_dir=profiles_dir, data_dir=data_dir)
        except Exception as exc:  # noqa: BLE001 — isolate blast radius: a sibling's broken
            # profile (missing dir, malformed YAML, bad config) must NEVER crash the reader's
            # own report run. Best-effort read of another agent's optional context → warn+skip.
            logger.warning("sibling %r skipped: profile failed to load (%s)", entry.id, exc)
            continue
        if other.project_group == self_group:
            siblings.append(entry.id)
    return siblings


def read_sibling_facts(sibling_ids: list[str], store: BaseStore) -> list[str]:
    """Read each sibling's stored facts from its `(id, "memory")` Store namespace.

    Namespace-scoped `store.search` (NOT a cross-prefix wildcard) so it works for both
    `InMemoryStore` and `PostgresStore`. Stops at `MAX_SIBLING_FACTS`.
    """
    facts: list[str] = []
    for sibling_id in sibling_ids:
        # `search` defaults to limit=10; request the full cap so MAX_SIBLING_FACTS is the
        # real bound (namespace-scoped, not a cross-prefix wildcard — works on both backends).
        for item in store.search((sibling_id, _NAMESPACE_KIND), limit=MAX_SIBLING_FACTS):
            fact = item.value.get("fact")
            if fact:
                facts.append(str(fact))
                if len(facts) >= MAX_SIBLING_FACTS:
                    return facts
    return facts


def build_sibling_context(
    loaded: LoadedProfile,
    settings: Settings,
    store: BaseStore,
    registry: tuple[RegistryEntry, ...],
    *,
    profiles_dir: Path | None = None,
    data_dir: Path | None = None,
) -> tuple[tuple[str, ...], object | None]:
    """Build the `(sibling_facts, selector)` pair for a `ProfileContext`.

    Returns `((), None)` — WITHOUT constructing an `LlmClient` — when the profile has no
    `project_group`, no siblings resolve, or no sibling facts exist. The selector is wired
    in S2 (`sibling_selector.make_llm_selector`); S1 ships facts + a `None` selector.
    """
    if loaded.project_group is None:
        return (), None
    ids = enumerate_siblings(
        loaded.profile_id, loaded.project_group, registry,
        profiles_dir=profiles_dir, data_dir=data_dir,
    )
    if not ids:
        return (), None
    facts = read_sibling_facts(ids, store)
    if not facts:
        return (), None
    return tuple(facts), None  # selector paired in S2
