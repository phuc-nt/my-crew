"""v8 M23: the gateway auto-approve wiring (surface 2 — gateway-enqueue Lớp B). Offline.

The security-critical invariants: an auto-approved action re-enters _execute(approved=True) so
Lớp A hard-deny, the kill-switch, and dry-run ALL still apply; the daily cap is enforced via
the gateway; and with no config the behavior is byte-identical to pre-M23 (queues).
"""

from __future__ import annotations

import pathlib
from dataclasses import replace

import pytest

from my_crew.actions.action_gateway import ActionGateway, HardBlockedError, WriteDisabledError
from my_crew.config.config_builders import build_settings_from_dict

CFG = {
    "actions": {"slack_post": {"enabled": True, "max_per_day": 2, "channels": ["C_EXT"]}},
    "trusted_senders": {"telegram": ["999"]},
}


def _settings(tmp_path, **over):
    s = build_settings_from_dict({"trust_mode": "guarded"})
    over.setdefault("dry_run", False)
    return replace(s, data_dir=pathlib.Path(tmp_path), **over)


def _gw(tmp_path, *, auto=CFG, **over):
    # Two external channels: C_EXT is granted in CFG, C_EXT2 is external (⇒ Lớp B) but NOT
    # granted — so a post to C_EXT2 is a real Lớp B action the trust ladder must still queue.
    return ActionGateway(_settings(tmp_path, **over),
                         external_channels=frozenset({"C_EXT", "C_EXT2"}), auto_approve=auto)


def _post(text="x", channel="C_EXT"):
    return {"type": "mcp_tool", "server": "slack", "tool": "post_message",
            "args": {"channel": channel, "text": text}}


def _handler(a):
    return "posted"


# --- surface 2: scheduled-origin auto (via execute → needs_interrupt) ---


def test_scheduled_external_post_auto_executes(tmp_path):
    gw = _gw(tmp_path)
    r = gw.execute(_post(), handler=_handler, rationale="scheduled report")
    assert r.status == "executed"
    gw.close()


def test_no_config_queues_like_pre_m23(tmp_path):
    gw = _gw(tmp_path, auto=None)
    r = gw.execute(_post(), handler=_handler, rationale="s")
    assert r.status == "pending_approval"  # byte-identical to before the trust ladder
    gw.close()


def test_wrong_destination_queues(tmp_path):
    # C_EXT2 is external (⇒ Lớp B) but not in the grant's channels ⇒ auto refused ⇒ queue.
    gw = _gw(tmp_path)
    r = gw.execute(_post(channel="C_EXT2"), handler=_handler, rationale="s")
    assert r.status == "pending_approval"
    gw.close()


def test_daily_cap_via_gateway(tmp_path):
    gw = _gw(tmp_path)  # max_per_day 2
    a = gw.execute(_post("a"), handler=_handler, rationale="s")
    b = gw.execute(_post("b"), handler=_handler, rationale="s")
    c = gw.execute(_post("c"), handler=_handler, rationale="s")
    assert (a.status, b.status, c.status) == ("executed", "executed", "pending_approval")
    gw.close()


# --- the invariant: Lớp A / kill-switch / dry-run re-apply on the auto path (B2) ---


def test_kill_switch_denies_even_with_auto_on(tmp_path):
    gw = _gw(tmp_path, write_disabled=True)
    with pytest.raises(WriteDisabledError):
        gw.execute(_post(), handler=_handler, rationale="s")
    gw.close()


def test_dry_run_applies_on_auto_path(tmp_path):
    gw = _gw(tmp_path, dry_run=True)
    r = gw.execute(_post(), handler=_handler, rationale="s")
    assert r.status == "dry_run"  # auto got past the interrupt but dry-run still stops it
    gw.close()


def test_hard_deny_lop_a_never_auto(tmp_path):
    # a destructive gh command is Lớp A hard-deny; auto config must not let it through.
    gw = _gw(tmp_path)
    hard = {"type": "gh_cli", "command": "gh api -X DELETE /repos/o/r"}
    with pytest.raises(HardBlockedError):
        gw.execute(hard, handler=_handler, rationale="s")
    gw.close()


# --- surface 2: chat-origin auto (via enqueue_for_approval) ---


def test_chat_trusted_dm_auto_executes(tmp_path):
    gw = _gw(tmp_path)
    r = gw.enqueue_for_approval(_post(), reason="chat cmd", sender_id="999",
                                transport="telegram", chat_id="999", auto_handler=_handler)
    assert r.status == "executed"
    gw.close()


def test_chat_stranger_queues(tmp_path):
    gw = _gw(tmp_path)
    r = gw.enqueue_for_approval(_post(), reason="chat", sender_id="000",
                                transport="telegram", chat_id="000", auto_handler=_handler)
    assert r.status == "pending_approval"
    gw.close()


def test_chat_group_queues(tmp_path):
    gw = _gw(tmp_path)
    r = gw.enqueue_for_approval(_post(), reason="chat", sender_id="999",
                                transport="telegram", chat_id="GRP", auto_handler=_handler)
    assert r.status == "pending_approval"
    gw.close()


def test_chat_without_handler_queues(tmp_path):
    # no auto_handler ⇒ can't execute ⇒ queue (never a silent no-op)
    gw = _gw(tmp_path)
    r = gw.enqueue_for_approval(_post(), reason="chat", sender_id="999",
                                transport="telegram", chat_id="999")
    assert r.status == "pending_approval"
    gw.close()


def test_propose_only_no_handler_queues_not_skips(tmp_path):
    # A propose-only call (handler=None, e.g. the automation ProposeStep) must QUEUE for a
    # human even with auto on — never take the auto branch, no-op, and burn a slot (review MED).
    gw = _gw(tmp_path)
    r = gw.execute(_post(), handler=None, rationale="propose only")
    assert r.status == "pending_approval"
    gw.close()


def test_chat_hard_deny_never_auto(tmp_path):
    gw = _gw(tmp_path)
    hard = {"type": "gh_cli", "command": "gh api -X DELETE /repos/o/r"}
    r = gw.enqueue_for_approval(hard, reason="chat", sender_id="999", transport="telegram",
                                chat_id="999", auto_handler=_handler)
    assert r.status == "skipped"  # hard-denied, never queued nor auto-run
    gw.close()
