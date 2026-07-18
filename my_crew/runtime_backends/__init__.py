"""Agent runtime backends (v20).

`AgentRuntime` is the seam that decouples the agent-LOOP (how one employee produces its
result) from ORCHESTRATION (coordinator/ticker/team) and SAFETY (Action Gateway). It lets
the loop be the native one-shot graph today, a LangChain tool-calling loop tomorrow, or a
model-native agent next year — swapped behind this interface without the gateway or team
changing.

v20 Phase 1 ships the interface + `NativeGraphRuntime` (wraps the existing graph builders,
byte-identical). `create_agent`/`deep_agent` runtimes land in later phases; selecting one now
raises. The default is `native`, and `RUNTIME_FORCE_NATIVE=1` forces native fleet-wide
(kill-switch).
"""

from __future__ import annotations

from my_crew.runtime_backends.protocol import AgentRuntime, resolve_runtime

__all__ = ["AgentRuntime", "resolve_runtime"]
