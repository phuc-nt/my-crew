"""v3 M5 S4 RED LINE GATE: config-driven allowlist must NOT weaken THE INVARIANT.

The allowlist became pack-contributed. This suite is the hard gate proving that move
did not loosen the guardrail:
- Lớp A hard-deny (destructive/security) still fires even if a pack tries to allow it
  — the red line is core, not pack-overridable.
- default-DENY holds: a tool absent from the active allowlist is denied.
- A pack's allowlist genuinely governs the default-DENY layer (the seam is real).
- PM's pack allowlist == the core default ⇒ byte-identical classification.
"""

from __future__ import annotations

from my_crew.actions.hard_block import (
    _DEFAULT_MCP_ALLOWLIST,
    BlockCategory,
    classify,
)
from my_crew.packs import PackRegistry


def _mcp(server, tool, **extra):
    return {"type": "mcp_tool", "server": server, "tool": tool, "args": extra}


# --- Lớp A is core and NOT pack-overridable ---


def test_pack_cannot_allowlist_a_destructive_tool():
    # A malicious/buggy pack lists a delete tool. Lớp A (data-loss marker) denies it
    # REGARDLESS — the allowlist only governs the default-DENY layer beneath the red line.
    evil = {"confluence": ("deletepage",)}
    verdict = classify(_mcp("confluence", "deletePage"), allowlist=evil)
    assert verdict.blocked
    assert verdict.category == BlockCategory.DATA_LOSS


def test_pack_cannot_allowlist_a_security_tool():
    evil = {"confluence": ("setrestriction",)}
    verdict = classify(_mcp("confluence", "setRestriction"), allowlist=evil)
    assert verdict.blocked
    assert verdict.category == BlockCategory.SECURITY


# --- default-DENY holds under a custom allowlist ---


def test_tool_not_in_pack_allowlist_is_denied():
    # Pack permits only slack post_message; a confluence write is denied by default.
    al = {"slack": ("post_message",)}
    verdict = classify(_mcp("confluence", "createPage"), allowlist=al)
    assert verdict.blocked
    assert verdict.category == BlockCategory.NOT_ALLOWLISTED


def test_unknown_server_is_denied_by_default():
    al = {"slack": ("post_message",)}
    verdict = classify(_mcp("hubspot", "create_contact"), allowlist=al)
    assert verdict.blocked
    assert verdict.category == BlockCategory.NOT_ALLOWLISTED


# --- the allowlist seam is real: a pack's list actually permits ---


def test_pack_allowlist_permits_its_own_safe_tool():
    al = {"gsheets": ("append_row",)}  # a hypothetical HR-style safe write
    verdict = classify(_mcp("gsheets", "append_row"), allowlist=al)
    assert not verdict.blocked


def test_default_none_uses_core_pm_allowlist():
    # No allowlist passed ⇒ the core PM default governs (byte-identical pre-v3).
    assert not classify(_mcp("slack", "post_message")).blocked
    assert classify(_mcp("gsheets", "append_row")).blocked  # not in PM default


# --- PM pack == core default (byte-identical classification) ---


def test_pm_pack_allowlist_classifies_identically_to_default():
    pm_allowlist = PackRegistry().load("pm").allowlist
    samples = [
        _mcp("slack", "post_message"),
        _mcp("confluence", "createPage"),
        _mcp("jira", "addComment"),
        _mcp("linear", "linear_createComment"),
        _mcp("confluence", "deletePage"),  # red line
        _mcp("slack", "delete_message"),  # red line
        _mcp("hubspot", "create_contact"),  # default-deny
    ]
    for action in samples:
        with_pack = classify(action, allowlist=pm_allowlist)
        with_default = classify(action, allowlist=_DEFAULT_MCP_ALLOWLIST)
        assert with_pack.blocked == with_default.blocked
        assert with_pack.category == with_default.category
