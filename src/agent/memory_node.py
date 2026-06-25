"""The `remember` graph node — extract + persist agent memory (v2 M2-P8 Slice 3).

Runs AFTER `deliver` on the INTERNAL report graphs. On a real internal delivery it:
1. extracts salient facts from the report (injectable extractor — LLM by default),
2. writes each fact to the LangGraph Store under `(agent_id, "memory")` keyed by a
   content hash (identical facts across runs dedupe), and
3. mirrors the facts into MEMORY.md's agent section (human-visible + the read path for
   the next run, via the existing P2 injection).

Gated: writes NOTHING unless the run actually delivered AND is internal AND not a
dry-run — there is nothing to remember from a skipped/dry/external report. This is
INTERNAL agent state: it does NOT go through the Action Gateway (the gateway governs
EXTERNAL mutations only). The node never imports ActionGateway.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from src.agent.memory_extractor import MemoryExtractor
from src.agent.memory_mirror import write_memory_file

_NAMESPACE_KIND = "memory"


def make_memory_node(
    *,
    extractor: MemoryExtractor,
    agent_id: str,
    memory_path: Path | None,
    audience: str,
    settings,
):
    """Build the `remember` node closure.

    `store` is read from the node's `store=` param (injected by the compiled graph).
    `memory_path` is the agent's MEMORY.md path. The node returns
    `{"memory_written": n}` for observability (n = facts persisted; 0 when gated out).
    """

    def remember(state, *, store=None) -> dict:
        # Gate: only a real internal delivery is worth remembering.
        if audience != "internal" or settings.dry_run or not state.get("delivered"):
            return {"memory_written": 0}
        report_text = state.get("report_text", "")
        if not report_text.strip():
            return {"memory_written": 0}

        facts = extractor(report_text)
        if not facts:
            return {"memory_written": 0}

        ts = datetime.now(UTC).isoformat()
        if store is not None:
            for fact in facts:
                key = hashlib.sha256(fact.encode("utf-8")).hexdigest()[:16]
                store.put((agent_id, _NAMESPACE_KIND), key, {"fact": fact, "ts": ts})

        if memory_path is not None:
            write_memory_file(memory_path, facts)
        return {"memory_written": len(facts)}

    return remember


def add_remember_node(builder, remember) -> None:
    """Rewire `deliver → remember → END` (replaces the direct `deliver → END` edge).

    The single wiring site shared by the 3 report builders. Call AFTER the builder has
    added its nodes/edges but BEFORE compile; the caller must NOT also add `deliver → END`.
    """
    from langgraph.graph import END

    builder.add_node("remember", remember)
    builder.add_edge("deliver", "remember")
    builder.add_edge("remember", END)


def build_remember_node(profile_id: str, settings, audience: str):
    """Build the `remember` node for an agent (None on the external path).

    The node self-gates (internal + delivered + not-dry-run), so building it for an
    external run is harmless — but external never injects/uses memory, so we skip it
    there to keep the external graph identical to pre-P8. The LLM extractor is built
    from the per-agent settings; agent_id + MEMORY.md path come from `profile_id`.
    """
    if audience != "internal":
        return None
    from src.agent.memory_extractor import make_llm_extractor
    from src.llm.client import LlmClient
    from src.profile.loader import profile_memory_path

    return make_memory_node(
        extractor=make_llm_extractor(LlmClient(settings)),
        agent_id=profile_id,
        memory_path=profile_memory_path(profile_id),
        audience=audience,
        settings=settings,
    )
