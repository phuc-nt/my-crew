"""pm-pack write surface (v3 M5 S4): allowlist contribution + write handlers.

The PM domain contributes its `ALLOWLIST` — the MCP server→tool names PM may write to.
The gateway threads this into `classify(..., allowlist=...)` as the default-DENY surface.
It is identical to the core's pre-v3 default, so PM behavior is byte-identical. A pack can
only *add* permitted tools here; it can NEVER widen the Lớp A red line (destructive/
security markers stay in core `hard_block.py`, are checked first, and are not
pack-overridable).

Write-handler DISPATCH stays in core (`my_crew/actions/approved_dispatch.py`): the handlers
(slack/confluence/linear/email) are shared gateway primitives reused across domains (M6's
HR pack posts to Slack too), so the pack does not own handler callables — it only
declares the allowlist. A domain-specific handler, if ever needed, is added then (YAGNI).
"""

from __future__ import annotations

# Permitted MCP writes for PM — server → tool names (case-insensitive at match time).
# Mirrors the core default so pm-pack is byte-identical; the gateway enforces it as the
# default-DENY allowlist. Destructive tools are intentionally absent (and hit Lớp A
# regardless). Keep `pack.yaml` `servers:` in sync with these keys.
ALLOWLIST: dict[str, tuple[str, ...]] = {
    "slack": ("post_message", "post_message_blocks", "update_message"),
    "confluence": ("createpage", "updatepage"),
    "jira": ("addcomment", "createissue"),
    "linear": ("linear_createcomment",),
}
