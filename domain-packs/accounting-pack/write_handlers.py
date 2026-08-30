"""accounting-pack write handlers + allowlist (P6).

`ALLOWLIST` stays empty: this pack's one write, `append_ledger_row`, is a NATIVE
`gws_write`-typed chat command (see commands.py) — not an `mcp_tool` action, so it never
belongs in this ALLOWLIST (which only governs mcp_tool-type actions; see
my_crew/packs/registry.py::_load_commands and hr-pack/write_handlers.py for the same
precedent/split). `append_ledger_row` is guarded by default (must be explicitly enabled
per-agent, same posture as hr-pack's sheet append) and always routes through the
ActionGateway → hard_block's fixed `_GWS_ALLOWLIST_PREFIXES` table.
"""

from __future__ import annotations

#: server → permitted write tool names. Empty ⇒ no mcp_tool-type writes in this pack.
ALLOWLIST: dict[str, tuple[str, ...]] = {}
