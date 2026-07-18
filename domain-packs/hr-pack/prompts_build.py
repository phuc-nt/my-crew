"""hr-pack prompt builder (v3 M6 S3).

Builds the LLM messages for the headcount narrative. The system prompt is a pack asset
(`prompts/headcount-narrative-system.md`, loaded via the same `load_pack_prompt` the PM
pack uses); the builder logic lives here in the pack. The LLM writes ONLY the qualitative
narrative — every count is rendered deterministically by the analyzer (Phase-1 lesson).

Persona/project/memory are injected on the INTERNAL path exactly as PM does, reusing the
core `prepend_persona` / `build_context_block` (so the external PII red line is identical).
"""

from __future__ import annotations

from my_crew.packs.registry import load_pack_prompt
from my_crew.profile.context import build_context_block, prepend_persona

_SYSTEM = load_pack_prompt("hr", "headcount-narrative-system")
_EXTERNAL_SYSTEM = load_pack_prompt("hr", "headcount-narrative-external-system")


def build_headcount_narrative_messages(
    report, *, report_date: str, audience: str = "internal",
    persona: str = "", project: str = "", memory: str = "",
) -> list[dict]:
    """Messages for the headcount narrative.

    Feeds the model the DETERMINISTIC counts as context and asks for a short qualitative
    summary — it must not invent numbers. For `audience="external"` the external system
    prompt (stakeholder tone, high-level only) is authoritative and project/memory are
    NOT injected — the same PII red line PM uses (internal facts never reach a
    stakeholder summary). Both audiences see aggregate counts only (no names).
    """
    status_lines = "\n".join(f"- {g.label}: {g.count}" for g in report.by_status)
    dept_lines = "\n".join(f"- {g.label}: {g.count}" for g in report.by_department)
    facts = (
        f"Ngày báo cáo: {report_date}\n"
        f"Tổng nhân sự: {report.total}\n\n"
        f"Theo trạng thái:\n{status_lines or '- (không có)'}\n\n"
        f"Theo phòng ban:\n{dept_lines or '- (không có)'}"
    )
    if audience == "external":
        # External: stakeholder-tone, no project/memory injection (internal-fact red line).
        system = _EXTERNAL_SYSTEM
        user = (
            "Dưới đây là số liệu nhân sự tổng hợp. Viết MỘT đoạn cập nhật ngắn (2-3 câu) "
            "cho stakeholder về tình hình nhân sự ở mức TỔNG QUAN — KHÔNG con số chi tiết "
            f"theo phòng ban, chỉ nêu quy mô + xu hướng chung.\n\n{facts}"
        )
    else:
        system = prepend_persona(_SYSTEM, persona)
        user = (
            f"{build_context_block(project, memory)}Dưới đây là số liệu nhân sự đã tính "
            "sẵn. Viết MỘT đoạn tóm tắt định tính ngắn (2-4 câu) về tình hình nhân sự — "
            f"KHÔNG lặp lại con số cụ thể (bảng đã có riêng), chỉ nêu xu hướng.\n\n{facts}"
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
