"""`ToolProvider`: how a domain pack reads its source systems (v3 M5 seam 2).

A graph builder must not import `jira_read`/`github_read` directly — that is the PM
coupling M5 removes. Instead it receives the active pack's `ToolProvider` and asks it
to read. The interface is deliberately **transport-agnostic**: it assumes only
"read a source → return normalized records", NOT *how* the read happens (MCP stdio,
`gh` CLI, or an HTTP API). This matters for M6: the HR pack adds a Google Sheets
adapter (HTTP, unlike anything PM uses) and must slot in here without the core
learning what Google Sheets is. If this interface baked in "MCP + gh CLI", M6 would
be stuck — so it intentionally does not.

S1 defines the contract only. S3 binds the PM provider (wrapping the existing jira/
github/confluence reads); S6 settles the normalized return type on the generic
`Task`/`Event` models. Until then the return is left as `Any` so the contract can be
introduced without forcing the data-model move early.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ToolProvider(Protocol):
    """Read a domain's source systems into normalized records for the graph.

    `read(kind, config, settings)` returns whatever the analyzers for `kind` consume
    — today the PM-shaped perceive payload, converging on generic `Task`/`Event`
    (S6). Implementations own their own transport (MCP spawn, CLI, HTTP); the core
    never inspects it. Implementations also own their own credentials, resolved
    env-only (`token_env`), never passed through the core.
    """

    def read(self, kind: str, config: Any, settings: Any) -> Any: ...
