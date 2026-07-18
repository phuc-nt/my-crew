"""External (stakeholder) audience system prompts — shared across report families.

Phase 5 audience-split: the `external` audience uses a business register that omits
internal detail (issue keys, PR numbers, assignee names, labor cost). These system
prompt strings are the only audience-specific constants; the builder functions that
use them live in each `*_report_prompt.py` module. Kept here so those modules stay
under the 200-LOC limit and the external tone is defined in one place.
"""

from __future__ import annotations

from my_crew.packs.registry import load_pack_prompt

# v3 M5 S5: the external-audience system-prompt strings moved into pm-pack assets
# (`domain-packs/pm-pack/prompts/*-external-system.md`), read verbatim so the composed
# external prompts stay byte-identical. The builder functions that use them stay in
# each `*_report_prompt.py`.
REPORT_EXTERNAL_SYSTEM = load_pack_prompt("pm", "report-external-system")
DETAIL_EXTERNAL_SYSTEM = load_pack_prompt("pm", "report-detail-external-system")
OKR_NARRATIVE_EXTERNAL_SYSTEM = load_pack_prompt("pm", "okr-narrative-external-system")
RESOURCE_NARRATIVE_EXTERNAL_SYSTEM = load_pack_prompt("pm", "resource-narrative-external-system")
