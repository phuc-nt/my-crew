"""Memory-fact extraction from a report (v2 M2-P8 Slice 3).

A `MemoryExtractor` is a callable `(report_text) -> list[str]` returning short, salient
project facts worth remembering across report runs (e.g. "Sprint 4 slipped due to the
auth migration"). The default impl asks the injectable `LlmClient`; tests inject a FAKE
extractor so the non-deterministic LLM step is isolated and the rest of the memory
pipeline (Store + MEMORY.md mirror) is deterministic + offline-testable.

The facts are INTERNAL memory only — never sent to an external audience (MEMORY.md is
injected into internal reports only, P2), so the extraction prompt forbids secrets and
the facts stay project-state notes, not credentials.

RESIDUAL RISK (accepted): the extracted facts are unfiltered LLM output — the prompt
forbids secrets but nothing enforces it, and memory persists + re-injects across runs
(wider exposure than a one-shot report). Internal-only confines the blast radius;
hardening (a secret-scrub before persist) is deferred. Mirrors the accepted Atlassian-
token residual-risk posture (pattern-undetectable secrets in free text).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from my_crew.llm.client import LlmClient

logger = logging.getLogger(__name__)

MemoryExtractor = Callable[[str], list[str]]
#: Cost-aware extractor: returns the facts AND the extraction call's cost, so a caller that
#: must account for the LLM spend (the team-step capture path) can fold it into the step total.
CostedMemoryExtractor = Callable[[str], "tuple[list[str], float | None]"]

_SYSTEM = (
    "Bạn trích các SỰ KIỆN dự án đáng nhớ xuyên các báo cáo (sprint trượt, quyết định, "
    "rủi ro lặp lại). Trả về TỐI ĐA 5 gạch đầu dòng NGẮN, mỗi dòng một sự kiện, tiếng Việt. "
    "TUYỆT ĐỐI không kèm token/khóa/bí mật, không số liệu nhạy cảm. Nếu không có gì đáng nhớ, "
    "trả về dòng trống."
)


def make_llm_costed_extractor(client: LlmClient) -> CostedMemoryExtractor:
    """Extractor that also reports its call cost: `(facts, cost_usd)`.

    Cost is None when the call failed (facts=[]) or the provider reported no cost. The
    team-step capture path folds this into the step's total so a captured cost includes the
    remember-extraction spend rather than silently omitting it.
    """

    def _extract(report_text: str) -> tuple[list[str], float | None]:
        try:
            result = client.complete(
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": report_text},
                ]
            )
            return _parse_facts(result.content), result.cost_usd
        except Exception as exc:  # noqa: BLE001 — memory is best-effort; never break a run
            logger.warning("memory extraction skipped (LLM unavailable): %s", exc)
            return [], None

    return _extract


def make_llm_extractor(client: LlmClient) -> MemoryExtractor:
    """Default extractor: ask the LLM for salient facts; tolerate failure (return []).

    Thin facts-only wrapper over the costed extractor (DRY) for the report path, which does
    not account for the extraction cost separately.
    """
    costed = make_llm_costed_extractor(client)

    def _extract(report_text: str) -> list[str]:
        facts, _cost = costed(report_text)
        return facts

    return _extract


def _parse_facts(content: str) -> list[str]:
    """Split the LLM reply into clean fact lines (strip bullets / blanks)."""
    facts: list[str] = []
    for line in content.splitlines():
        cleaned = line.strip().lstrip("-•* ").strip()
        if cleaned:
            facts.append(cleaned)
    return facts
