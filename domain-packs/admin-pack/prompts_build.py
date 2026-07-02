"""admin-pack narrative message builder (v3 M8).

Same shape as hr-pack's: the system prompt is a pack ASSET (prompts/*.md via
`load_pack_prompt`), persona prepended internal-only, deterministic report data goes
in the user message as compact JSON. Admin reports are internal-only in practice, but
the audience rule is honored anyway: external gets no persona/project/memory.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from domain_pack_admin.analyzers import FleetReport

from src.packs.registry import load_pack_prompt
from src.profile.context import build_context_block, prepend_persona


def build_admin_narrative_messages(
    report: FleetReport, *, report_date: str, audience: str = "internal",
    persona: str = "", project: str = "", memory: str = "",
) -> list[dict[str, str]]:
    system = load_pack_prompt("admin", "admin-narrative-system")
    if audience != "external":
        system = prepend_persona(system, persona)
    data = json.dumps(asdict(report), ensure_ascii=False)
    user = f"Ngày báo cáo: {report_date}\nDỮ LIỆU (đã tính sẵn):\n{data}"
    if audience != "external":
        context = build_context_block(project, memory)
        if context:
            user = f"{context}\n\n{user}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
