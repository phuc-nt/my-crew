"""admin-pack ToolProvider (v3 M8): read the fleet's own state.

Conforms to `src.packs.tool_provider.ToolProvider` — one `read(kind, config,
settings)` returning normalized records. The "transport" here is the platform itself:
the generic read-only accessor `agent_state_reader` (core). Admin sees every registry
agent; it can never write to one (the accessor is read-only by construction and this
pack's allowlist contains only its own Slack posts).
"""

from __future__ import annotations

from typing import Any


class AdminToolProvider:
    """Fleet reads for every admin report kind: one snapshot of all agents' state."""

    def read(self, kind: str, config: Any, settings: Any) -> dict[str, Any]:
        from src.runtime.agent_state_reader import read_all_agent_states, team_alerts

        states = read_all_agent_states()
        # Alerts ride along so every kind can surface them; analyzers slice per kind.
        return {"agents": states, "alerts": team_alerts(states)}


#: The pack's tool provider instance. Loaded by PackRegistry into Pack.tools.
TOOL_PROVIDER = AdminToolProvider()
