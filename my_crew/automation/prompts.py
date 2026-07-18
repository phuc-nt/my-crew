"""Bundled named-prompt registry for `analyze` steps (v2 M3-P12 D3).

An `analyze` step references a prompt by NAME (`prompt: analyze_impact`), never a free-text
body in the yaml. This is the ONLY source of analyze-prompt text, so a workflow file cannot
inject arbitrary LLM instructions — the prompt-injection surface is the fixed set below.

To add a prompt: add a (name -> text) entry here and document it. Keep prompts task-scoped
(PM analysis), instruction-only, and free of any tool authority.
"""

from __future__ import annotations

# name -> system/instruction prompt text. Vietnamese-leaning to match the agent's voice.
_NAMED_PROMPTS: dict[str, str] = {
    "analyze_impact": (
        "Bạn là PM. Dựa trên dữ liệu issue được cung cấp, tóm tắt NGẮN GỌN tác động của "
        "vấn đề này tới tiến độ sprint và stakeholder (2-3 câu). Chỉ nêu fact từ dữ liệu, "
        "không bịa. Không đề xuất hành động ghi."
    ),
    "summarize_blockers": (
        "Bạn là PM. Liệt kê các blocker nổi bật từ dữ liệu được cung cấp, mỗi blocker 1 dòng "
        "với mức ưu tiên. Ngắn gọn, chỉ dựa trên fact, không bịa."
    ),
}


def named_prompt(name: str) -> str:
    """Return the registered prompt text for `name`, or raise if unknown (fail closed)."""
    try:
        return _NAMED_PROMPTS[name]
    except KeyError:
        known = ", ".join(sorted(_NAMED_PROMPTS))
        raise ValueError(
            f"unknown analyze prompt {name!r}; known named prompts: {known}"
        ) from None


def is_known_prompt(name: str) -> bool:
    """True when `name` is a registered named prompt (used by schema validation)."""
    return name in _NAMED_PROMPTS
