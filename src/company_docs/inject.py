"""Render opted-in Company Docs into the INTERNAL compose prompt (v7 M19).

The red line is identical to skills (`skill_selector.select_skill_text`): external audience →
"" (no injection), so a company document — which may hold PII or internal policy — never
reaches an external report or message. Unlike skills there is NO LLM selector: every doc the
agent opted into is injected (the CEO already chose relevance by ticking it), bounded by a
character budget so the context can't blow up. Truncation is DECLARED, never silent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.company_docs.store import CompanyDoc

#: Total budget for the injected block. Docs are added whole until the next would overflow;
#: the remainder is dropped with an explicit marker (bounded, declared — red-team MINOR-5).
MAX_INJECT_CHARS = 12_000
_TRUNCATED = "\n\n[đã lược bớt tài liệu do vượt giới hạn ngữ cảnh]"


def render_company_docs(docs: list[CompanyDoc]) -> str:
    """Wrap opted-in doc bodies in a `<company_docs>` block, bounded by MAX_INJECT_CHARS.

    Docs are included whole in order until the next would exceed the budget; if any are
    dropped, a truncation marker is appended so the omission is visible, not silent. Empty
    list ⇒ "" (byte-identical to no-docs)."""
    if not docs:
        return ""
    parts: list[str] = []
    used = 0
    truncated = False
    for doc in docs:
        block = f"## {doc.title}\n{doc.body.strip()}"
        if parts and used + len(block) > MAX_INJECT_CHARS:
            truncated = True
            break
        parts.append(block)
        used += len(block)
    if not parts:
        return ""
    body = "\n\n".join(parts)
    if truncated:
        body += _TRUNCATED
    return f"<company_docs>\n{body}\n</company_docs>"


def company_docs_text(context, audience: str) -> str:
    """The injectable text for this agent, or "" when the red line blocks it.

    External audience or no opted-in docs ⇒ "" (mirrors `select_skill_text`'s guard). The
    docs come pre-resolved on the ProfileContext (`company_docs`), so this stays offline.
    """
    docs = getattr(context, "company_docs", None)
    if audience != "internal" or not docs:
        return ""
    return render_company_docs(list(docs))
