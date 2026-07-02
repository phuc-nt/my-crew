"""admin-pack write surface (v3 M8 S4): allowlist contribution.

Admin delivers a short Slack digest — nothing else. Slack-only on purpose: fleet
digests are operational notes, no Confluence detail page in M8. The dispatch handlers
stay in core (`approved_dispatch.py`), exactly as PM/HR.

RED LINE: admin READS every agent's state but its write surface is only its own Slack
posts. There is deliberately NO tool here (and none exists in core) that could
approve/reject/trigger/modify another agent — cross-agent mutation stays impossible,
and a destructive marker still hits Lớp A regardless.
"""

from __future__ import annotations

# Permitted MCP writes for admin — Slack post/update only (server → tool names).
ALLOWLIST: dict[str, tuple[str, ...]] = {
    "slack": ("post_message", "post_message_blocks", "update_message"),
}
