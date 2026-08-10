"""Hybrid collect launcher (v75 phase 3) — Hermes' "no-LLM launcher → inject JSON →
agent does only the thinking" pattern applied to `needs_web` collect steps.

The launcher (this module, pure code) runs 1-3 web searches BEFORE the step's prompt
is built and hands the formatted bundle to the native one-shot tier, so most collect
steps skip the 100-400s tool-calling loop entirely. Measured stake: collects were the
largest remaining wall-clock cost after v74.

Safety shape: same `WebSearchConfig` gates + audit trail the in-loop search uses (no
new egress, no new permissions); FAIL-OPEN — any outcome without at least one clean
result set returns "" and the step runs its old tool-loop tier unchanged.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Cap on launcher searches per step — 3 queries cover a 2-3-entity fanned collect.
MAX_PREFETCH_QUERIES = 3


def derive_queries(step: Any) -> list[str]:
    """1-3 queries from the step title, no LLM call.

    The title is already a decent query (the same signal `build_search_query` keys
    on); when it carries a comma/`và` entity list — the fan-out rule REQUIRES entity
    names in collect titles — later entities get their own topic-prefixed query so
    the first entity's results can't crowd the rest out of one search's result page.
    """
    title = str(getattr(step, "title", "") or "").strip()
    if not title:
        return []
    entities = _listed_entities(title)
    if len(entities) < 1:
        return [title]
    topic = _topic_words(title, entities)
    extra = [f"{topic} {e}".strip() for e in entities[: MAX_PREFETCH_QUERIES - 1]]
    return [title, *extra][:MAX_PREFETCH_QUERIES]


def _listed_entities(title: str) -> list[str]:
    """Comma/`và`-separated items AFTER the first one (the first stays fused with the
    head phrase inside the title itself, which the base query already covers)."""
    parts = [p for chunk in title.split(",") for p in re.split(r"\s+và\s+", chunk)]
    items = [p.strip(" .;:–-") for p in parts[1:]]
    return [i for i in items if i and 1 <= len(i.split()) <= 6]


def _topic_words(title: str, entities: list[str]) -> str:
    """First few title words that belong to no listed entity — the verb/topic phrase
    ('Thu thập giá ...') that keeps a bare entity name from being an aimless query."""
    entity_words = {w.lower() for e in entities for w in e.split()}
    words = [w for w in title.split() if w.lower().strip(",()") not in entity_words]
    return " ".join(words[:5])


def prefetch_for_step(loaded: Any, settings: Any, step: Any) -> str:
    """Run the launcher searches; return the formatted context bundle, or "" (fail-open).

    "" whenever the agent lacks the `web_search:` opt-in, no provider key exists, or
    NO query returned a clean result set — the step then keeps its tool-loop tier.
    Queries that individually failed still get their 3-path sentinel line in the
    bundle (phase-1 guard: a partial outage must read as THIẾU-do-nguồn, not as
    'dữ liệu không tồn tại')."""
    return prefetch_queries(loaded, settings, derive_queries(step))


def prefetch_queries(
    loaded: Any, settings: Any, queries: list[str], *, keep_sentinels: bool = False,
) -> str:
    """Same launcher, but over CALLER-CHOSEN queries.

    v77 sprint mode drives this directly: its pipeline picks queries per entity and
    then again per coverage gap, which `derive_queries` (title-only, one shot) cannot
    express. Same gates, same audit trail — the only thing that moves is who decides
    what to search for.

    `keep_sentinels` changes what a TOTAL failure returns. The default "" exists so a
    collect step can fall back to its tool loop, which will do its own searching — for
    that caller the sentinels are noise. A sprint step has no such fallback: for it, ""
    is indistinguishable from "we never searched", and it would then report a provider
    outage as "đã tìm nhưng không có dữ liệu" — the exact confusion between THIẾU-do-
    nguồn and dữ liệu-không-tồn-tại this module exists to prevent. With the flag, the
    sentinel lines survive so the caller can report the real reason.
    """
    if loaded is None or not getattr(loaded, "web_search", False):
        return ""
    queries = [q.strip() for q in queries if q and q.strip()]
    if not queries:
        return ""
    from my_crew.audit.audit_log import AuditLog
    from my_crew.runtime.team_task_paths import team_tasks_root
    from my_crew.tools.search_result_formatter import format_search_results
    from my_crew.tools.web_search_tool import WebSearchConfig, web_search_outcome

    config = WebSearchConfig(
        tavily_api_key=getattr(settings, "tavily_api_key", None),
        brave_api_key=getattr(settings, "brave_api_key", None),
    )
    if not config.available():
        return ""

    audit_log = AuditLog(team_tasks_root() / "audit" / "audit.jsonl")
    actor = Path(str(getattr(settings, "data_dir", ""))).name
    blocks: list[str] = []
    any_ok = False
    for query in queries:
        try:
            results, status = web_search_outcome(
                query, config=config, audit_log=audit_log, actor=actor,
            )
        except Exception:  # noqa: BLE001 — launcher must never kill the step
            logger.warning("collect prefetch: query failed hard, falling back", exc_info=True)
            return ""
        if results:
            any_ok = True
            text, _count, _quarantined = format_search_results(results)
            blocks.append(f"KẾT QUẢ TÌM KIẾM (truy vấn: {query}):\n{text}")
        elif status == "provider_error":
            blocks.append(
                f"[LỖI NGUỒN TÌM KIẾM] (truy vấn: {query}) Không truy cập được web "
                "search — phần dữ liệu tương ứng ghi THIẾU DO NGUỒN LỖI, không được "
                "kết luận 'dữ liệu không tồn tại'."
            )
        elif status == "empty":
            blocks.append(
                f"[KHÔNG CÓ KẾT QUẢ] (truy vấn: {query}) Nguồn hoạt động bình thường "
                "nhưng không có kết quả — nhiều khả năng dữ liệu không có công khai; "
                "ghi THIẾU kèm lý do đó."
            )
        # skipped_sensitive/empty_query: contribute nothing, matching the in-loop hook.
    if not any_ok and not keep_sentinels:
        return ""
    return "\n\n".join(blocks)
