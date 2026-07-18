"""v8 M23 trust ladder: the pure auto-approve policy + daily-slot reservation. Offline.

The policy is the security core — it decides whether a Lớp B action skips the human queue.
These lock the matrix: origin, action-type, destination-bound grant, trusted-sender (Telegram
DM only), and the local-date cap reservation.
"""

from __future__ import annotations

from datetime import datetime

from my_crew.actions.auto_approve_policy import (
    RATIONALE_PREFIX,
    claim_daily_slot,
    evaluate,
)
from my_crew.actions.dedup_store import DedupStore

CFG = {
    "actions": {"slack_post": {"enabled": True, "max_per_day": 2, "channels": ["C_EXT"]}},
    "trusted_senders": {"telegram": ["999"]},
}
POST = {"type": "mcp_tool", "tool": "post_message", "args": {"channel": "C_EXT"}}
NOW = datetime(2026, 7, 4, 12, 0)


# --- evaluate: scheduled origin ---


def test_scheduled_allowed_when_type_enabled_and_dest_matches():
    d = evaluate(POST, CFG, origin="scheduled")
    assert d.allowed and d.rationale == f"{RATIONALE_PREFIX}scheduled:slack_post"


def test_no_config_never_allows():
    assert not evaluate(POST, None, origin="scheduled").allowed
    assert not evaluate(POST, {}, origin="scheduled").allowed


def test_type_not_enabled_queues():
    cfg = {"actions": {"slack_post": {"enabled": False, "max_per_day": 5}}}
    assert not evaluate(POST, cfg, origin="scheduled").allowed


def test_unknown_action_type_never_allows():
    weird = {"type": "gh_cli", "command": "gh pr merge"}
    assert not evaluate(weird, CFG, origin="scheduled").allowed


def test_destination_not_in_grant_queues():
    other = {"type": "mcp_tool", "tool": "post_message", "args": {"channel": "C_OTHER"}}
    d = evaluate(other, CFG, origin="scheduled")
    assert not d.allowed and "đích" in d.reason


def test_grant_without_channels_allows_any_dest():
    cfg = {"actions": {"slack_post": {"enabled": True, "max_per_day": 5}}}  # no channels key
    other = {"type": "mcp_tool", "tool": "post_message", "args": {"channel": "C_ANY"}}
    assert evaluate(other, cfg, origin="scheduled").allowed


# --- evaluate: chat origin ---


def test_chat_trusted_telegram_dm_allowed():
    d = evaluate(POST, CFG, origin="chat", sender_id="999", transport="telegram", chat_id="999")
    assert d.allowed and d.rationale == f"{RATIONALE_PREFIX}trusted_sender:999"


def test_chat_stranger_queues():
    d = evaluate(POST, CFG, origin="chat", sender_id="000", transport="telegram", chat_id="000")
    assert not d.allowed and "tin cậy" in d.reason


def test_chat_group_not_dm_queues():
    # a Telegram DM has chat_id == sender id; a group chat differs → not auto
    d = evaluate(POST, CFG, origin="chat", sender_id="999", transport="telegram", chat_id="GRP")
    assert not d.allowed and "DM" in d.reason


def test_chat_non_telegram_transport_queues():
    d = evaluate(POST, CFG, origin="chat", sender_id="999", transport="slack", chat_id="999")
    assert not d.allowed and "Telegram" in d.reason


def test_chat_empty_chat_id_never_auto():
    # defense-in-depth: a trusted sender with a BLANK chat_id must not skip the DM binding
    d = evaluate(POST, CFG, origin="chat", sender_id="999", transport="telegram", chat_id="")
    assert not d.allowed and "DM" in d.reason


def test_chat_empty_sender_id_never_auto():
    d = evaluate(POST, CFG, origin="chat", sender_id="", transport="telegram", chat_id="999")
    assert not d.allowed


def test_scheduled_origin_ignores_trusted_senders():
    # a scheduled report has no sender; it does not need to be in trusted_senders
    cfg = {"actions": {"slack_post": {"enabled": True, "max_per_day": 5, "channels": ["C_EXT"]}}}
    assert evaluate(POST, cfg, origin="scheduled").allowed


# --- claim_daily_slot: the cap reservation ---


def test_cap_exhausts_after_max_per_day(tmp_path):
    dedup = DedupStore(tmp_path / "d.db")
    assert claim_daily_slot(dedup, POST, CFG, now=NOW) is True   # slot 1
    assert claim_daily_slot(dedup, POST, CFG, now=NOW) is True   # slot 2
    assert claim_daily_slot(dedup, POST, CFG, now=NOW) is False  # cap (max 2)


def test_cap_resets_next_local_day(tmp_path):
    dedup = DedupStore(tmp_path / "d.db")
    day1 = datetime(2026, 7, 4, 12, 0)
    day2 = datetime(2026, 7, 5, 12, 0)
    claim_daily_slot(dedup, POST, CFG, now=day1)
    claim_daily_slot(dedup, POST, CFG, now=day1)
    assert claim_daily_slot(dedup, POST, CFG, now=day1) is False  # day1 exhausted
    assert claim_daily_slot(dedup, POST, CFG, now=day2) is True   # day2 has fresh slots


def test_cap_survives_a_new_store_instance(tmp_path):
    # the reservation is durable (SQLite) — a restart must not reset the cap
    p = tmp_path / "d.db"
    d1 = DedupStore(p)
    assert claim_daily_slot(d1, POST, CFG, now=NOW) and claim_daily_slot(d1, POST, CFG, now=NOW)
    d1.close()
    d2 = DedupStore(p)  # "restart"
    assert claim_daily_slot(d2, POST, CFG, now=NOW) is False  # cap remembered


def test_zero_max_per_day_never_claims(tmp_path):
    dedup = DedupStore(tmp_path / "d.db")
    cfg = {"actions": {"slack_post": {"enabled": True, "max_per_day": 0, "channels": ["C_EXT"]}}}
    assert claim_daily_slot(dedup, POST, cfg, now=NOW) is False
