"""Pack-declared MCP server spawn gate (v20 Phase 5, red-team SEC#4).

A community domain pack can declare its own MCP servers (so a new domain brings its own
tools without a core change). But an MCP server is spawned as a real subprocess (`node
<dist>`) with the agent's environment — so a hostile pack could name
`mcp_dist: ./node_modules/evil/index.js` and get arbitrary code executed with inherited
tokens, entirely below the Action Gateway. The tool-NAME allowlist does NOT stop this — it
governs which writes pass the gateway, not which binaries get spawned.

This gate validates a pack-declared MCP dist path BEFORE it can be spawned:
  - must be an ABSOLUTE path (no relative paths that resolve against the pack dir),
  - must NOT live under a user-writable/pack directory (no shipping the binary inside the
    pack itself),
  - must be on an operator-approved allowlist (env `PACK_MCP_ALLOWED_DIST`, colon-separated
    absolute paths) — default-deny: with no allowlist, NO pack-declared MCP server spawns.

Profile-level `integrations:` (operator-authored, M3-P11) is unchanged — the operator writing
their own profile is trusted; a third-party pack is not.
"""

from __future__ import annotations

import os
from pathlib import Path


class PackMcpDenied(RuntimeError):
    """A pack-declared MCP server was refused by the spawn gate."""


def _allowed_dist_paths() -> set[str]:
    """Operator-approved absolute dist paths (env PACK_MCP_ALLOWED_DIST, ':'-separated)."""
    raw = os.environ.get("PACK_MCP_ALLOWED_DIST", "").strip()
    if not raw:
        return set()
    return {str(Path(p).resolve()) for p in raw.split(":") if p.strip()}


def assert_pack_mcp_allowed(pack_id: str, server_name: str, mcp_dist: str) -> None:
    """Raise PackMcpDenied unless a pack-declared MCP dist path is operator-approved.

    Default-deny: an empty allowlist refuses every pack-declared server (the operator must opt
    each one in). Relative paths and paths inside the pack tree are always refused.
    """
    if not mcp_dist or not mcp_dist.strip():
        raise PackMcpDenied(
            f"pack {pack_id!r} server {server_name!r}: mcp_dist trống — không cho spawn."
        )
    p = Path(mcp_dist)
    if not p.is_absolute():
        raise PackMcpDenied(
            f"pack {pack_id!r} server {server_name!r}: mcp_dist {mcp_dist!r} là đường dẫn "
            f"tương đối — chỉ chấp nhận absolute path đã được operator duyệt."
        )
    resolved = str(p.resolve())
    allowed = _allowed_dist_paths()
    if resolved not in allowed:
        raise PackMcpDenied(
            f"pack {pack_id!r} server {server_name!r}: mcp_dist {resolved!r} chưa nằm trong "
            f"allowlist operator (env PACK_MCP_ALLOWED_DIST). Default-deny — thêm path để cho phép."
        )


def scrubbed_pack_mcp_env(required_env: list[str]) -> dict[str, str]:
    """Minimal env for a pack-declared MCP subprocess — only PATH/HOME + explicitly-listed vars.

    A pack server does NOT inherit the full process environment (which holds OPENROUTER_API_KEY,
    Telegram/Atlassian tokens). It gets PATH + HOME plus only the env var NAMES the pack declared
    in `required_env` and the operator actually set — nothing else leaks to third-party code.
    """
    env = {k: os.environ[k] for k in ("PATH", "HOME") if k in os.environ}
    for name in required_env:
        if name in os.environ:
            env[name] = os.environ[name]
    return env
