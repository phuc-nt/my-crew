"""RED LINE: office-pack's empty allowlist must mean default-deny, never "no
allowlist configured" (which would silently widen to the CORE default allowlist).

The coordinator (office-pack) performs no external write of its own — the two things
it does (update team_task_store rows, spawn a `team-step` worker subprocess) never
touch the Action Gateway — so `pack.yaml` declares `servers: []` and
`write_handlers.ALLOWLIST = {}` on purpose. The regression this guards against:
`mcp_allowlist=pack.allowlist or None` — in Python, `{} or None` evaluates to `None`,
and `classify(action, allowlist=None)` falls back to the wider CORE (PM) default
allowlist. An empty dict must therefore be threaded through AS an empty dict, never
coalesced away, or a step could smuggle a live MCP write through the coordinator's
"empty" allowlist and land on the PM default's permitted tools instead.
"""

from __future__ import annotations

import pytest

from my_crew.actions.hard_block import BlockCategory, classify
from my_crew.packs import PackRegistry


def _mcp(server, tool, **extra):
    return {"type": "mcp_tool", "server": server, "tool": tool, "args": extra}


def test_office_pack_allowlist_is_an_empty_dict_not_none():
    pack = PackRegistry().load("office")
    assert pack.allowlist == {}
    assert pack.allowlist is not None


def test_office_pack_manifest_declares_no_servers():
    import yaml

    from my_crew.config.settings import REPO_ROOT

    manifest = yaml.safe_load(
        (REPO_ROOT / "domain-packs" / "office-pack" / "pack.yaml").read_text(encoding="utf-8")
    )
    assert manifest.get("servers") == []


def test_office_pack_empty_allowlist_denies_every_mcp_tool():
    # Even tools the CORE default permits (e.g. slack post_message) must be denied
    # under office-pack's own (empty) allowlist — the coordinator has no write surface.
    office_allowlist = PackRegistry().load("office").allowlist
    samples = [
        _mcp("slack", "post_message"),
        _mcp("confluence", "createPage"),
        _mcp("jira", "addComment"),
        _mcp("linear", "linear_createComment"),
        _mcp("gsheets", "append_row"),
    ]
    for action in samples:
        verdict = classify(action, allowlist=office_allowlist)
        assert verdict.blocked
        assert verdict.category == BlockCategory.NOT_ALLOWLISTED


def test_office_pack_allowlist_still_denies_a_redline_tool():
    # Lớp A is core, never pack-overridable — proven again here specifically against
    # the office-pack allowlist (an empty dict changes nothing about this layer).
    office_allowlist = PackRegistry().load("office").allowlist
    verdict = classify(_mcp("confluence", "deletePage"), allowlist=office_allowlist)
    assert verdict.blocked
    assert verdict.category == BlockCategory.DATA_LOSS


def test_empty_dict_or_none_coalescing_bug_would_change_behavior():
    # Demonstrates WHY `pack.allowlist or None` must never be used: passing the
    # coalesced value (None) instead of the real empty dict changes a tool's verdict
    # from denied to allowed — proving the two are NOT behaviorally interchangeable,
    # which is exactly the regression `write_handlers.py`'s docstring warns against.
    action = _mcp("slack", "post_message")  # permitted under the CORE default
    denied_with_real_empty_dict = classify(action, allowlist={})
    allowed_with_coalesced_none = classify(action, allowlist=({} or None))
    assert denied_with_real_empty_dict.blocked is True
    assert allowed_with_coalesced_none.blocked is False


def test_office_pack_allowlist_used_by_a_real_gateway_still_denies(settings_factory, tmp_path):
    # Wire the pack's actual allowlist into a real ActionGateway (not just `classify`
    # directly) to prove the seam holds end to end, mirroring how a coordinator-owned
    # gateway would be constructed if one were ever added. A NOT_ALLOWLISTED verdict
    # raises HardBlockedError (there is no "denied" GatewayResult status) — the
    # gateway never silently returns a soft failure for a blocked write.
    from my_crew.actions.action_gateway import ActionGateway, HardBlockedError
    from my_crew.audit.audit_log import AuditLog

    office_allowlist = PackRegistry().load("office").allowlist
    settings = settings_factory()
    gateway = ActionGateway(
        settings=settings,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        mcp_allowlist=office_allowlist,
    )
    with pytest.raises(HardBlockedError):
        gateway.execute(_mcp("slack", "post_message"))
