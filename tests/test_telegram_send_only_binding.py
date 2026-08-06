"""A send-only Telegram binding lets an agent SPEAK on a bot it must never READ.

Why this exists: the coordinator reports to the CEO through the same bot the CEO
delegated to (Pong), rather than through a third voice. Sharing a bot token is only safe
in one direction. Telegram serves ONE hanging `getUpdates` per token, so a second poller
would 409 against the real owner — and the loser of that race can still consume and ack
a message the owner never handled, silently eating the CEO's request. Sending has no
such contention.

`poll_minutes: 0` is that declaration. These tests pin both halves: the send path stays
open, and every reader entry point stays shut. There are TWO independent readers — the
scheduled `inbox` pseudo-kind and the long-poll listener thread — and missing either one
reopens the whole hazard, so both are asserted here.
"""

from __future__ import annotations

import pytest

from my_crew.config.config_builders_channels import build_telegram
from my_crew.runtime.inbox_dispatch import (
    has_any_inbox,
    inbox_poll_minutes,
    run_all_inboxes,
    telegram_reader,
)


def _profile(poll_minutes, *, profile_id="coordinator", inbox=None):
    """A minimal profile stub carrying just the telegram binding under test."""
    telegram = build_telegram(
        {"telegram": {"bot_token_env": "PONG_TELEGRAM_BOT_TOKEN",
                      "chat_ids": ["5248565986"], "poll_minutes": poll_minutes}}
    )
    config = type("Config", (), {"telegram": telegram})()
    return type("Loaded", (), {"profile_id": profile_id, "config": config, "inbox": inbox})()


def test_send_only_is_accepted_by_the_config_builder():
    """`0` must survive config parsing — it is a declaration, not a bad cadence."""
    telegram = _profile(0).config.telegram
    assert telegram.poll_minutes == 0
    assert telegram.bot_token_env == "PONG_TELEGRAM_BOT_TOKEN"
    assert telegram.chat_ids == ("5248565986",), "the send allowlist must stay intact"


def test_a_negative_cadence_is_still_rejected():
    """Only 0 means send-only; below that is a typo and must fail loud."""
    with pytest.raises(RuntimeError, match="poll_minutes"):
        build_telegram({"telegram": {"bot_token_env": "X", "chat_ids": ["1"],
                                     "poll_minutes": -1}})


def test_the_scheduler_synthesizes_no_inbox_tick():
    """`has_any_inbox` gates the `inbox` pseudo-kind. True here would schedule an agent
    to poll a bot it does not own."""
    assert has_any_inbox(_profile(0)) is False
    assert telegram_reader(_profile(0)) is None


def test_a_polling_binding_is_untouched():
    """The guard must not disturb every ordinary agent — pong still reads its own bot."""
    polling = _profile(1, profile_id="pong")
    assert has_any_inbox(polling) is True
    assert telegram_reader(polling) is not None
    assert inbox_poll_minutes(polling) == 1


def test_the_dispatcher_runs_no_telegram_poll(monkeypatch):
    """Belt to the scheduler's braces: even if something dispatches an `inbox` tick to a
    send-only agent, no `getUpdates` may go out on the borrowed token."""
    polled = []
    monkeypatch.setattr(
        "my_crew.runtime.telegram_inbox.run_telegram_inbox",
        lambda loaded, settings: polled.append(loaded.profile_id),
    )
    with pytest.raises(RuntimeError, match="no inbox"):
        run_all_inboxes(_profile(0), object())
    assert polled == [], "a send-only binding was polled"


def test_a_send_only_agent_gets_no_listener_thread(monkeypatch):
    """The second reader. The listener long-polls independently of the scheduler, so
    gating only `has_any_inbox` would leave the 409 hazard fully intact."""
    from my_crew.runtime import service

    coordinator = _profile(0, profile_id="coordinator")
    pong = _profile(1, profile_id="pong")
    by_id = {"coordinator": coordinator, "pong": pong}

    monkeypatch.setattr(
        service, "load_registry",
        lambda: [type("E", (), {"id": i, "enabled": True})() for i in by_id],
    )
    monkeypatch.setattr(service, "load_profile", lambda i: by_id[i])
    for stub in by_id.values():
        stub.enabled = True

    started = []
    monkeypatch.setattr(
        "my_crew.runtime.telegram_listener.start_telegram_listeners",
        lambda agents, run_inbox_worker: started.extend(a[0] for a in agents) or [],
    )
    service.Service().start_telegram_listeners()

    assert started == ["pong"], "the send-only agent got a long-poll listener"
