"""One inbound message is handled once, even when its handling has side effects.

The production failure this locks down: the CEO sent pong ONE Telegram message asking for
a market study. Two readers saw the same update 72 seconds apart — the per-agent long-poll
listener thread and the scheduled `inbox` tick, which coexist deliberately as mutual
fallback — and TWO near-identical team tasks were created. Only ONE reply went out, so from
the chat it looked like it had worked.

That asymmetry is the whole diagnosis. The gateway's idempotency claim (step 5) fires when
the REPLY is sent, and the chat-ops branch creates the team task BEFORE composing that
reply. So the second run did its damage and was then silenced at the door on the way out.
The guard has to sit at intake, in front of every branch, keyed on the message's own
immutable id.

These tests assert the invariant through `answer_mention` — the single funnel both readers
go through — rather than through either reader, so the property holds no matter which pair
of callers races next.
"""

from __future__ import annotations

from my_crew.actions.action_gateway import ActionGateway
from my_crew.agent.qa_answer import answer_mention
from my_crew.config.config_builders import (
    build_reporting_config_from_dict,
    build_settings_from_dict,
)
from my_crew.profile.loader import LoadedProfile

_TOKEN_ENV = "TG_TEST_BOT_TOKEN"


def _msg(uid, text="nghiên cứu giúp anh thị trường xe điện", *, chat="111"):
    return {"ts": f"tg:{chat}:{uid}", "text": text, "channel": chat, "user": "42",
            "transport": "telegram", "message_id": uid, "chat_type": "private",
            "update_id": uid}


def _loaded(tmp_path, *, profile_id="pong"):
    settings = build_settings_from_dict(
        {"openrouter_api_key": "k", "data_dir": tmp_path, "dry_run": False}
    )
    config = build_reporting_config_from_dict({
        "jira_project_key": "SCRUM", "github_repo": "o/r", "slack_report_channel": "C_REP",
        "slack_stakeholder_channel": "", "slack_external_channels": "",
        "telegram": {"bot_token_env": _TOKEN_ENV, "chat_ids": ["111"]},
    })
    return LoadedProfile(
        profile_id=profile_id, name=profile_id, enabled=True, settings=settings,
        config=config, soul="", project="", memory="", schedule={},
        reports=("daily",), domain="personal", inbox=None,
    )


class _StubTools:
    def read(self, kind, config, settings):
        return {}


class _StubPack:
    commands = {}
    prompts = {}
    allowlist = {}
    tools = _StubTools()
    report_kinds = {"daily": None}


class _Llm:
    def complete(self, messages, **_kw):
        return type("R", (), {"content": "đã ghi nhận", "cost_usd": None})()


def _sink(monkeypatch):
    """Count outbound Bot API sends. Returns the mutable counter."""
    monkeypatch.setenv(_TOKEN_ENV, "tok")
    count = {"n": 0}
    monkeypatch.setattr(
        "my_crew.actions.telegram_write.api_call",
        lambda t, m, p=None: count.update(n=count["n"] + 1) or {"message_id": 9},
    )
    return count


def test_side_effects_before_the_reply_happen_only_once(tmp_path, monkeypatch):
    """The exact production shape: handling MUTATES STATE and only then replies.

    `_maybe_handle_ops` stands in for the real chat-ops branch, which creates a team task
    before returning its confirmation text. Under the old send-time-only dedup, both runs
    reached this side effect and only the second reply was suppressed — one confirmation,
    two tasks. The claim now has to stop the second run before it ever gets here.
    """
    _sink(monkeypatch)
    tasks_created = []
    monkeypatch.setattr(
        "my_crew.agent.qa_answer._maybe_handle_ops",
        lambda *a, **k: (tasks_created.append("task") or "Đã giao đội.", None),
    )

    loaded = _loaded(tmp_path)
    gw = ActionGateway(loaded.settings, external_channels=frozenset())
    try:
        mention = _msg(15)
        first, _ = answer_mention(loaded, loaded.settings, mention=mention,
                                  pack=_StubPack(), gateway=gw, llm=_Llm())
        second, _ = answer_mention(loaded, loaded.settings, mention=mention,
                                   pack=_StubPack(), gateway=gw, llm=_Llm())
    finally:
        gw.close()

    assert len(tasks_created) == 1, (
        f"one message created {len(tasks_created)} team tasks — the duplicate reached the "
        "side effect before being deduped"
    )
    assert first.status == "executed"
    assert second.status == "deduplicated"


def test_the_claim_survives_a_restart(tmp_path, monkeypatch):
    """The two readers are separate PROCESSES, so an in-memory guard would not have
    helped. A fresh gateway on the same data dir must still see the message as taken."""
    _sink(monkeypatch)
    handled = []
    monkeypatch.setattr(
        "my_crew.agent.qa_answer._maybe_handle_ops",
        lambda *a, **k: (handled.append(1) or "ok", None),
    )

    loaded = _loaded(tmp_path)
    mention = _msg(16)
    statuses = []
    for _ in range(2):  # two independent gateways = two processes over one dedup.db
        gw = ActionGateway(loaded.settings, external_channels=frozenset())
        try:
            outcome, _ = answer_mention(loaded, loaded.settings, mention=mention,
                                        pack=_StubPack(), gateway=gw, llm=_Llm())
            statuses.append(outcome.status)
        finally:
            gw.close()

    assert len(handled) == 1
    assert statuses == ["executed", "deduplicated"]


def test_a_second_agent_watching_the_same_chat_still_answers(tmp_path, monkeypatch):
    """The claim must dedup an AGENT against itself, never one agent against another.

    Two agents legitimately read the same chat (observed in production: `thu-ky` answered
    a message `pong` had also answered). A claim keyed on the message alone would let
    whichever agent ran first silence the other entirely.
    """
    _sink(monkeypatch)
    handled = []
    monkeypatch.setattr(
        "my_crew.agent.qa_answer._maybe_handle_ops",
        lambda loaded, *a, **k: (handled.append(loaded.profile_id) or "ok", None),
    )

    mention = _msg(17)
    statuses = []
    for agent_id in ("pong", "thu-ky"):
        # Separate data dirs — this is how the fleet really lays out per-agent stores.
        loaded = _loaded(tmp_path / agent_id, profile_id=agent_id)
        gw = ActionGateway(loaded.settings, external_channels=frozenset())
        try:
            outcome, _ = answer_mention(loaded, loaded.settings, mention=mention,
                                        pack=_StubPack(), gateway=gw, llm=_Llm())
            statuses.append(outcome.status)
        finally:
            gw.close()

    assert handled == ["pong", "thu-ky"]
    assert statuses == ["executed", "executed"]


def test_a_duplicate_does_not_consume_the_per_poll_reply_budget(tmp_path, monkeypatch):
    """A poll answers at most `_MAX_REPLIES_PER_POLL` messages. A deduped message sent
    nothing, so counting it would let a burst of duplicates push real messages to the
    next poll — re-introducing the very latency the tick fix removed."""
    from my_crew.runtime import telegram_inbox
    from my_crew.runtime.telegram_inbox import run_telegram_inbox, save_offset

    _sink(monkeypatch)
    monkeypatch.setattr(
        "my_crew.agent.qa_answer._maybe_handle_ops", lambda *a, **k: ("ok", None)
    )
    monkeypatch.setattr(telegram_inbox, "_MAX_REPLIES_PER_POLL", 2)

    loaded = _loaded(tmp_path)
    fresh = _msg(23, "câu hỏi mới")
    dupes = [_msg(20), _msg(21), _msg(22)]
    monkeypatch.setattr(
        "my_crew.tools.telegram_read.fetch_new_updates",
        lambda telegram, offset: (dupes + [fresh], [], 24),
    )
    save_offset(loaded.settings.data_dir, 20)

    # Claim the three duplicates the way the other reader would have.
    gw = ActionGateway(loaded.settings, external_channels=frozenset())
    try:
        for m in dupes:
            answer_mention(loaded, loaded.settings, mention=m, pack=_StubPack(),
                           gateway=gw, llm=_Llm())
    finally:
        gw.close()

    monkeypatch.setattr("my_crew.packs.registry.PackRegistry.load", lambda self, d: _StubPack())
    out = run_telegram_inbox(loaded, loaded.settings)

    assert out["replied"] == 1, "the fresh message was starved by deduped ones"
