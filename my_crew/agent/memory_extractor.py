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
import re
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
    "TUYỆT ĐỐI không kèm token/khóa/bí mật, không số liệu nhạy cảm. KHÔNG ghi diễn biến "
    "quy trình nội bộ (trễ tiến độ, tắc nghẽn thẩm định, đề xuất xin quyền/phê duyệt, "
    "kiến nghị can thiệp) — chúng không phải fact về dự án và đọc lại sẽ làm agent tưởng "
    "mình bị nghẽn/thiếu quyền ở việc sau. Nếu không có gì đáng nhớ, trả về CHUỖI RỖNG "
    "(không viết chữ 'dòng trống')."
)


def make_llm_costed_extractor(
    client: LlmClient, *, system: str = _SYSTEM
) -> CostedMemoryExtractor:
    """Extractor that also reports its call cost: `(facts, cost_usd)`.

    Cost is None when the call failed (facts=[]) or the provider reported no cost. The
    team-step capture path folds this into the step's total so a captured cost includes the
    remember-extraction spend rather than silently omitting it. `system` cho phép call-site
    đổi tiêu chí "đáng nhớ" (mặc định: sự kiện dự án; chat thư ký dùng prompt riêng — v57 P5).
    """

    def _extract(report_text: str) -> tuple[list[str], float | None]:
        try:
            result = client.complete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": report_text},
                ],
                role="util",
            )
            return _parse_facts(result.content), result.cost_usd
        except Exception as exc:  # noqa: BLE001 — memory is best-effort; never break a run
            logger.warning("memory extraction skipped (LLM unavailable): %s", exc)
            return [], None

    return _extract


def make_llm_extractor(client: LlmClient, *, system: str = _SYSTEM) -> MemoryExtractor:
    """Default extractor: ask the LLM for salient facts; tolerate failure (return []).

    Thin facts-only wrapper over the costed extractor (DRY) for the report path, which does
    not account for the extraction cost separately.
    """
    costed = make_llm_costed_extractor(client, system=system)

    def _extract(report_text: str) -> list[str]:
        facts, _cost = costed(report_text)
        return facts

    return _extract


#: Hard cap on facts per extraction — the prompt asks for ≤5 but nothing enforced it, so
#: a model that replayed the whole report flooded MEMORY.md in one write.
_MAX_FACTS = 5

#: A memory fact is one short declarative line. Everything else observed in a real
#: poisoning incident (researcher, 2026-08): markdown headers/tables/fences, numbered
#: "here is what I can do" offers, questions addressed to the user, and first-person
#: capability denials ("tôi không có khả năng tra cứu web") that then CAUSED the next
#: run to refuse — a self-reinforcing loop. These are filtered in code because the
#: extraction prompt alone demonstrably does not hold across models.
_JUNK_PREFIXES = ("#", "|", "```", ">", "*")
#: Capability denials AND permission-request framings. The second family is the subtler
#: relapse vector (observed live, task 8301d626e800): "Đề xuất cấp quyền tra cứu web" is
#: a perfectly declarative sentence, but re-reading it taught the agent that web access
#: needs approval — and the next fresh task opened with "Xin phép được duyệt cho phép
#: tra cứu web" while holding a working search tool.
_DENIAL_RE = re.compile(
    r"(không\s+có\s+khả\s+năng|không\s+thể\s+(truy\s+cập|duyệt\s+web|tra\s+cứu)"
    r"|xin\s+lỗi|xin\s+phép"
    r"|đề\s+xuất\s+(cấp\s+quyền|duyệt|phê\s+duyệt)|kiến\s+nghị)",
    re.IGNORECASE,
)
_NUMBERED_RE = re.compile(r"^\d+[.)]\s")
#: Literal placeholder junk some models emit instead of an empty reply.
_PLACEHOLDER_RE = re.compile(r"^\(?\s*(dòng\s+trống|empty\s+line)\s*\)?\.?$", re.IGNORECASE)


def _is_fact_line(line: str) -> bool:
    """One declarative, self-standing statement — not conversation debris."""
    if len(line) > 300:  # poison blocks were whole paragraphs; real facts are short
        return False
    if line.startswith(_JUNK_PREFIXES) or _NUMBERED_RE.match(line):
        return False
    if line.endswith(("?", ":")):  # questions/offers addressed to a person
        return False
    if _PLACEHOLDER_RE.match(line):
        return False
    return not _DENIAL_RE.search(line)


def _parse_facts(content: str) -> list[str]:
    """Split the LLM reply into clean fact lines (strip bullets, drop junk, cap count)."""
    facts: list[str] = []
    for line in content.splitlines():
        cleaned = line.strip().lstrip("-•* ").strip()
        if cleaned and _is_fact_line(cleaned):
            facts.append(cleaned)
    return facts[:_MAX_FACTS]
