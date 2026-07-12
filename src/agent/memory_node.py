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


def _assert_self_namespace(namespace: tuple[str, str], agent_id: str) -> None:
    """WO-self boundary (M3-P9 A3): an agent writes ONLY its own memory namespace.

    Cross-agent memory is READ-only (siblings read each other); writing is self-only.
    A namespace other than `(agent_id, "memory")` is a bug/misconfig — fail loud so it
    can never silently corrupt a sibling's facts.
    """
    expected = (agent_id, _NAMESPACE_KIND)
    if namespace != expected:
        raise PermissionError(
            f"memory write denied: {namespace!r} is not this agent's namespace "
            f"({expected!r}); agents write only their own memory."
        )


def make_memory_node(
    *,
    extractor: MemoryExtractor,
    agent_id: str,
    memory_path: Path | None,
    audience: str,
    settings,
    report_state_key: str = "report_text",
    costed: bool = False,
):
    """Build the `remember` node closure.

    `store` is read from the node's `store=` param (injected by the compiled graph).
    `memory_path` is the agent's MEMORY.md path. The node returns `{"memory_written": n}`
    for observability (n = facts persisted; 0 when gated out).

    `report_state_key` names the state field holding the text to extract from — `report_text`
    for the report graphs (default), `result_text` for the team-step graph. `costed=True`
    means `extractor` is a `CostedMemoryExtractor` returning `(facts, cost)`; the node then
    folds that cost into the returned `cost_usd` (prior step cost + extraction cost) so a
    downstream capture reflects the true per-attempt spend. `costed=False` keeps the report
    path byte-identical (extractor returns facts only; no cost field emitted).
    """

    def remember(state, *, store=None) -> dict:
        # Gate: only a real internal delivery is worth remembering.
        if audience != "internal" or settings.dry_run or not state.get("delivered"):
            return {"memory_written": 0}
        report_text = state.get(report_state_key, "")
        if not report_text.strip():
            return {"memory_written": 0}

        if costed:
            facts, extract_cost = extractor(report_text)
        else:
            facts, extract_cost = extractor(report_text), None
        if not facts:
            return {"memory_written": 0}

        ts = datetime.now(UTC).isoformat()
        if store is not None:
            namespace = (agent_id, _NAMESPACE_KIND)
            _assert_self_namespace(namespace, agent_id)  # WO-self: write only own memory
            for fact in facts:
                key = hashlib.sha256(fact.encode("utf-8")).hexdigest()[:16]
                store.put(namespace, key, {"fact": fact, "ts": ts})

        if memory_path is not None:
            write_memory_file(memory_path, facts)

        out: dict = {"memory_written": len(facts)}
        # Fold the extraction cost into the step total so capture stays honest (the extra LLM
        # call is part of what this attempt spent). Only when costed AND a cost was reported.
        if costed and extract_cost is not None:
            prior = state.get("cost_usd") or 0.0
            out["cost_usd"] = prior + extract_cost
        return out

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


def build_team_step_remember_node(self_id: str, settings):
    """Build the `remember` node for a team-step graph (extract from `result_text`).

    Team-step is inherently internal, so there is no audience gate here — but the node still
    self-gates on delivered + not-dry-run. Uses the COSTED extractor so the extraction call's
    spend folds into the step's cost (capture honesty). Returns None when `self_id` is blank
    (a step whose assignee is unknown has no MEMORY.md to write) so the graph keeps
    `deliver → END`.
    """
    if not self_id:
        return None
    from src.agent.memory_extractor import make_llm_costed_extractor
    from src.llm.client import LlmClient
    from src.profile.loader import profile_memory_path

    return make_memory_node(
        extractor=make_llm_costed_extractor(LlmClient(settings)),
        agent_id=self_id,
        memory_path=profile_memory_path(self_id),
        audience="internal",
        settings=settings,
        report_state_key="result_text",
        costed=True,
    )


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
