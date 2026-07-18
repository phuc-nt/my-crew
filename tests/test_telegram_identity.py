"""v6 M13: per-agent Telegram bot identity. Offline (Bot API + LLM stubbed).

Load-bearing properties:

- Chat allowlist is enforced on BOTH directions: the read layer drops updates from a
  non-allowlisted chat (but still acks them), and the send handler REFUSES a
  non-allowlisted destination on the real execution path.
- `telegram_send` goes through the full gateway: Lớp A secret scan, structural checks,
  dry-run, dedup. It never needs Lớp B (operator-declared internal chats), and the M12
  chat-command Lớp B semantics ride the transport unchanged.
- Watermark discipline mirrors M11: bootstrap acks backlog silently; INFRA errors hold
  the offset for retry; a poison message is skipped past; group chatter not addressed
  to the agent is consumed silently.
- No `telegram:` block ⇒ config is None ⇒ behavior byte-identical to pre-M13.
"""

from __future__ import annotations

import pytest

from my_crew.actions.action_gateway import ActionGateway
from my_crew.actions.hard_block import classify, needs_interrupt
from my_crew.actions.telegram_write import make_telegram_send_handler, send_telegram_message
from my_crew.config.config_builders import (
    build_reporting_config_from_dict,
    build_settings_from_dict,
)
from my_crew.config.telegram_config import TelegramConfig
from my_crew.profile.loader import LoadedProfile
from my_crew.runtime.telegram_inbox import load_offset, run_telegram_inbox, save_offset

_TOKEN_ENV = "TG_TEST_BOT_TOKEN"


def _telegram(chat_ids=("111",), poll=2):
    return TelegramConfig(bot_token_env=_TOKEN_ENV, chat_ids=tuple(chat_ids), poll_minutes=poll)


def _config(telegram: dict | None = None):
    d = {"jira_project_key": "SCRUM", "github_repo": "o/r", "slack_report_channel": "C_REP",
         "slack_stakeholder_channel": "", "slack_external_channels": ""}
    if telegram is not None:
        d["telegram"] = telegram
    return build_reporting_config_from_dict(d)


def _loaded(tmp_path, *, telegram: dict | None, inbox: dict | None = None):
    settings = build_settings_from_dict(
        {"openrouter_api_key": "k", "data_dir": tmp_path, "dry_run": False}
    )
    return LoadedProfile(
        profile_id="acme", name="Acme", enabled=True, settings=settings,
        config=_config(telegram), soul="", project="", memory="", schedule={},
        reports=("daily",), domain="pm", inbox=inbox,
    )


# --- config seam (S1) ---


def test_no_telegram_block_means_none_config():
    assert _config().telegram is None  # byte-identical pre-M13


def test_telegram_block_parses_and_validates():
    cfg = _config({"bot_token_env": _TOKEN_ENV, "chat_ids": "111, 222", "poll_minutes": 3})
    assert cfg.telegram.chat_ids == ("111", "222")
    assert cfg.telegram.poll_minutes == 3
    with pytest.raises(RuntimeError, match="chat_ids is empty"):
        _config({"bot_token_env": _TOKEN_ENV, "chat_ids": []})
    with pytest.raises(RuntimeError, match="poll_minutes"):
        _config({"bot_token_env": _TOKEN_ENV, "chat_ids": ["1"], "poll_minutes": 0})


# --- gateway classification (S2) ---


def test_classify_telegram_send_valid_is_allowed_and_not_lop_b():
    action = {"type": "telegram_send", "chat_id": "111", "text": "báo cáo ngày"}
    assert not classify(action).blocked
    assert not needs_interrupt(action).interrupt


@pytest.mark.parametrize(
    ("action", "match"),
    [
        ({"type": "telegram_send", "chat_id": "", "text": "x"}, "no chat_id"),
        ({"type": "telegram_send", "chat_id": "111", "text": "  "}, "empty text"),
    ],
)
def test_classify_telegram_send_structural_denies(action, match):
    verdict = classify(action)
    assert verdict.blocked and match in verdict.reason


def test_classify_telegram_send_blocks_secret_in_text():
    verdict = classify(
        {"type": "telegram_send", "chat_id": "111",
         "text": "token: xoxc-1234567890-abcdefghijklmnop"}
    )
    assert verdict.blocked and verdict.category.value == "credential"


def test_telegram_bot_token_is_a_detected_secret():
    """The credential class M13 itself introduces must be visible to Lớp A + audit
    redaction (review M1) — and normal report text must not false-match."""
    from my_crew.actions.secret_patterns import find_secret

    assert find_secret("token 123456789:AAHdqTcvbXH8s2vGoXaeqQFNvIhvbYZ6t-w lộ ra") is not None
    assert find_secret("SCRUM-123: deploy 10:35, build a1b2c3") is None
    verdict = classify(
        {"type": "telegram_send", "chat_id": "111",
         "text": "bot token là 123456789:AAHdqTcvbXH8s2vGoXaeqQFNvIhvbYZ6t-w"}
    )
    assert verdict.blocked and verdict.category.value == "credential"


# --- send handler: chat allowlist on the execution path (S2) ---


def test_handler_refuses_non_allowlisted_chat(monkeypatch):
    monkeypatch.setenv(_TOKEN_ENV, "tok")
    handler = make_telegram_send_handler(_telegram(chat_ids=("111",)))
    with pytest.raises(PermissionError, match="not in the agent's allowlisted"):
        handler({"chat_id": "999", "text": "hi"})


def test_handler_sends_to_allowlisted_chat(monkeypatch):
    monkeypatch.setenv(_TOKEN_ENV, "tok")
    calls = {}

    def fake_api(token, method, payload=None):
        calls.update(token=token, method=method, payload=payload)
        return {"message_id": 7}

    monkeypatch.setattr("my_crew.actions.telegram_write.api_call", fake_api)
    handler = make_telegram_send_handler(_telegram())
    out = handler({"chat_id": "111", "text": "hi", "reply_to_message_id": 5})
    assert calls["method"] == "sendMessage" and calls["payload"]["chat_id"] == "111"
    assert calls["payload"]["reply_parameters"]["message_id"] == 5
    assert "message 7" in out


def test_handler_fails_loud_when_token_env_unset(monkeypatch):
    monkeypatch.delenv(_TOKEN_ENV, raising=False)
    handler = make_telegram_send_handler(_telegram())
    with pytest.raises(RuntimeError, match="is not set"):
        handler({"chat_id": "111", "text": "hi"})


def test_send_telegram_message_truncates_and_refuses_empty(tmp_path, monkeypatch):
    monkeypatch.setenv(_TOKEN_ENV, "tok")
    sent = {}
    monkeypatch.setattr(
        "my_crew.actions.telegram_write.api_call",
        lambda t, m, p=None: sent.update(p=p) or {"message_id": 1},
    )
    settings = build_settings_from_dict(
        {"openrouter_api_key": "k", "data_dir": tmp_path, "dry_run": False}
    )
    gw = ActionGateway(settings, external_channels=frozenset())
    try:
        with pytest.raises(ValueError, match="empty"):
            send_telegram_message("  ", gateway=gw, telegram=_telegram(), chat_id="111",
                                  dedup_hint="t:1")
        result = send_telegram_message("x" * 5000, gateway=gw, telegram=_telegram(),
                                       chat_id="111", dedup_hint="t:2")
        assert result.status == "executed"
        assert len(sent["p"]["text"]) < 4096 and "cắt bớt" in sent["p"]["text"]
    finally:
        gw.close()


def test_dry_run_never_reaches_the_bot_api(tmp_path, monkeypatch):
    monkeypatch.setenv(_TOKEN_ENV, "tok")
    monkeypatch.setattr(
        "my_crew.actions.telegram_write.api_call",
        lambda *a, **k: pytest.fail("Bot API called under dry_run"),
    )
    settings = build_settings_from_dict(
        {"openrouter_api_key": "k", "data_dir": tmp_path, "dry_run": True}
    )
    gw = ActionGateway(settings, external_channels=frozenset())
    try:
        result = send_telegram_message("hi", gateway=gw, telegram=_telegram(),
                                       chat_id="111", dedup_hint="t:3")
        assert result.status == "dry_run"
    finally:
        gw.close()


# --- read layer: allowlist filter + offset (S2) ---


def _update(uid, chat_id, text, *, chat_type="private", message_id=None):
    return {"update_id": uid, "message": {
        "message_id": message_id or uid, "text": text,
        "chat": {"id": chat_id, "type": chat_type}, "from": {"id": 42},
    }}


def test_fetch_filters_foreign_chats_but_acks_them(monkeypatch):
    from my_crew.tools import telegram_read

    monkeypatch.setenv(_TOKEN_ENV, "tok")
    updates = [
        _update(10, 999, "from stranger"),          # foreign chat → dropped
        _update(11, 111, "hello"),                   # allowlisted
        {"update_id": 12, "message": {"chat": {"id": 111, "type": "private"},
                                      "message_id": 3}},  # non-text → dropped
    ]
    monkeypatch.setattr(telegram_read, "api_call", lambda t, m, p=None: updates)
    messages, next_offset = telegram_read.fetch_new_messages(_telegram(), offset=None)
    assert [m["text"] for m in messages] == ["hello"]
    assert messages[0]["ts"] == "tg:111:11" and messages[0]["transport"] == "telegram"
    assert next_offset == 13  # acks ALL updates incl. dropped ones


def test_fetch_empty_keeps_offset(monkeypatch):
    from my_crew.tools import telegram_read

    monkeypatch.setenv(_TOKEN_ENV, "tok")
    monkeypatch.setattr(telegram_read, "api_call", lambda t, m, p=None: [])
    assert telegram_read.fetch_new_messages(_telegram(), offset=5) == ([], None)


# --- poller (S3) ---


def _poller_env(tmp_path, monkeypatch, messages, next_offset):
    monkeypatch.setattr(
        "my_crew.tools.telegram_read.fetch_new_updates",
        lambda telegram, offset: (messages, [], next_offset),
    )
    return _loaded(tmp_path, telegram={"bot_token_env": _TOKEN_ENV, "chat_ids": ["111"]})


def test_poller_bootstrap_acks_backlog_without_answering(tmp_path, monkeypatch):
    """Bootstrap must fetch with offset=-1 (only the NEWEST pending update) so acking
    newest+1 confirms the whole backlog even past the 100-update page (review M2)."""
    seen = {}

    def _fetch(telegram, offset):
        seen["offset"] = offset
        return ([dict(ts="tg:111:20", text="old question", channel="111", user="42",
                      transport="telegram", message_id=20, chat_type="private",
                      update_id=20)], [], 21)

    monkeypatch.setattr("my_crew.tools.telegram_read.fetch_new_updates", _fetch)
    loaded = _loaded(tmp_path, telegram={"bot_token_env": _TOKEN_ENV, "chat_ids": ["111"]})
    monkeypatch.setattr(
        "my_crew.agent.qa_answer.answer_mention",
        lambda *a, **k: pytest.fail("bootstrap must not answer backlog"),
    )
    out = run_telegram_inbox(loaded, loaded.settings)
    assert out["status"] == "bootstrapped" and seen["offset"] == -1
    assert load_offset(loaded.settings.data_dir) == 21


def _msg(uid, text, *, chat="111", chat_type="private"):
    return {"ts": f"tg:{chat}:{uid}", "text": text, "channel": chat, "user": "42",
            "transport": "telegram", "message_id": uid, "chat_type": chat_type,
            "update_id": uid}


def test_poller_answers_dm_and_advances_offset(tmp_path, monkeypatch):
    loaded = _poller_env(tmp_path, monkeypatch, [_msg(30, "dự án sao rồi?")], 31)
    save_offset(loaded.settings.data_dir, 30)
    answered = []
    monkeypatch.setattr(
        "my_crew.agent.qa_answer.answer_mention",
        lambda ld, st, *, mention, pack, gateway: (
            answered.append(mention["ts"]),
            (type("R", (), {"status": "executed", "summary": "ok"})(), 0.001),
        )[1],
    )
    out = run_telegram_inbox(loaded, loaded.settings)
    assert answered == ["tg:111:30"] and out["replied"] == 1
    assert load_offset(loaded.settings.data_dir) == 31


def test_poller_group_message_without_mention_is_consumed_silently(tmp_path, monkeypatch):
    loaded = _poller_env(
        tmp_path, monkeypatch,
        [_msg(40, "chuyện phiếm nhóm", chat_type="group"),
         _msg(41, "@acme dự án sao rồi?", chat_type="group")],
        42,
    )
    save_offset(loaded.settings.data_dir, 40)
    answered = []
    monkeypatch.setattr(
        "my_crew.agent.qa_answer.answer_mention",
        lambda ld, st, *, mention, pack, gateway: (
            answered.append(mention["ts"]),
            (type("R", (), {"status": "executed", "summary": "ok"})(), None),
        )[1],
    )
    run_telegram_inbox(loaded, loaded.settings)
    assert answered == ["tg:111:41"]  # chatter skipped, mention answered
    assert load_offset(loaded.settings.data_dir) == 42


def test_poller_infra_error_holds_offset(tmp_path, monkeypatch):
    from my_crew.llm.fallback_policy import ProviderCallError

    loaded = _poller_env(tmp_path, monkeypatch, [_msg(50, "hỏi 1"), _msg(51, "hỏi 2")], 52)
    save_offset(loaded.settings.data_dir, 50)

    def _boom(*a, **k):
        raise ProviderCallError("all models down")

    monkeypatch.setattr("my_crew.agent.qa_answer.answer_mention", _boom)
    out = run_telegram_inbox(loaded, loaded.settings)
    assert out["replied"] == 0
    assert load_offset(loaded.settings.data_dir) == 50  # HELD — both retried next poll


def test_poller_poison_message_is_skipped_past(tmp_path, monkeypatch):
    loaded = _poller_env(tmp_path, monkeypatch, [_msg(60, "độc"), _msg(61, "lành")], 62)
    save_offset(loaded.settings.data_dir, 60)
    calls = []

    def _answer(ld, st, *, mention, pack, gateway):
        calls.append(mention["ts"])
        if mention["ts"] == "tg:111:60":
            raise RuntimeError("this one message is broken")
        return type("R", (), {"status": "executed", "summary": "ok"})(), None

    monkeypatch.setattr("my_crew.agent.qa_answer.answer_mention", _answer)
    out = run_telegram_inbox(loaded, loaded.settings)
    assert calls == ["tg:111:60", "tg:111:61"] and out["replied"] == 1
    assert load_offset(loaded.settings.data_dir) == 62


def test_poller_unreachable_api_holds_offset(tmp_path, monkeypatch):
    loaded = _loaded(tmp_path, telegram={"bot_token_env": _TOKEN_ENV, "chat_ids": ["111"]})
    save_offset(loaded.settings.data_dir, 70)

    def _down(telegram, offset):
        raise RuntimeError("telegram API getUpdates failed: 502")

    monkeypatch.setattr("my_crew.tools.telegram_read.fetch_new_updates", _down)
    out = run_telegram_inbox(loaded, loaded.settings)
    assert out["status"] == "telegram_unreachable"
    assert load_offset(loaded.settings.data_dir) == 70


def test_poller_write_disabled_holds_offset(tmp_path, monkeypatch):
    settings = build_settings_from_dict(
        {"openrouter_api_key": "k", "data_dir": tmp_path, "dry_run": False,
         "write_disabled": True}
    )
    loaded = _loaded(tmp_path, telegram={"bot_token_env": _TOKEN_ENV, "chat_ids": ["111"]})
    loaded = LoadedProfile(**{**loaded.__dict__, "settings": settings})
    save_offset(tmp_path, 80)
    monkeypatch.setattr(
        "my_crew.tools.telegram_read.fetch_new_updates",
        lambda telegram, offset: ([_msg(80, "hỏi")], [], 81),
    )
    out = run_telegram_inbox(loaded, settings)
    assert out["status"] == "writes_disabled"
    assert load_offset(tmp_path) == 80


# --- transport-agnostic answer path (S3) ---


def test_answer_mention_replies_via_telegram_send(tmp_path, monkeypatch):
    from my_crew.agent.qa_answer import answer_mention

    monkeypatch.setenv(_TOKEN_ENV, "tok")
    sent = {}
    monkeypatch.setattr(
        "my_crew.actions.telegram_write.api_call",
        lambda t, m, p=None: sent.update(p=p) or {"message_id": 9},
    )

    class _StubTools:
        def read(self, kind, config, settings):
            return {"issues": [{"key": "SCRUM-1", "status": "Done"}]}

    class _StubPack:
        commands = {}
        prompts = {}
        allowlist = {"slack": ("post_message",)}
        tools = _StubTools()
        report_kinds = {"daily": None}

    class _Llm:
        def complete(self, messages):
            return type("R", (), {"content": "SCRUM-1 đã Done. @acme", "cost_usd": 0.0001})()

    loaded = _loaded(tmp_path, telegram={"bot_token_env": _TOKEN_ENV, "chat_ids": ["111"]})
    mention = _msg(90, "tiến độ sao rồi?")
    outcome, cost = answer_mention(
        loaded, loaded.settings, mention=mention, pack=_StubPack(), llm=_Llm()
    )
    assert outcome.status == "executed" and cost == 0.0001
    assert sent["p"]["chat_id"] == "111"
    assert "@acme" not in sent["p"]["text"]  # sanitize applies on this transport too
    assert sent["p"]["reply_parameters"]["message_id"] == 90


def test_same_message_never_double_replies(tmp_path, monkeypatch):
    """Gateway dedup keyed on the immutable tg ts: a re-poll cannot double-send."""
    from my_crew.agent.qa_answer import answer_mention

    monkeypatch.setenv(_TOKEN_ENV, "tok")
    count = {"n": 0}
    monkeypatch.setattr(
        "my_crew.actions.telegram_write.api_call",
        lambda t, m, p=None: count.update(n=count["n"] + 1) or {"message_id": 9},
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
        def complete(self, messages):
            return type("R", (), {"content": "trả lời", "cost_usd": None})()

    loaded = _loaded(tmp_path, telegram={"bot_token_env": _TOKEN_ENV, "chat_ids": ["111"]})
    settings = loaded.settings
    gw = ActionGateway(settings, external_channels=frozenset())
    try:
        mention = _msg(95, "hỏi")
        first, _ = answer_mention(loaded, settings, mention=mention, pack=_StubPack(),
                                  gateway=gw, llm=_Llm())
        second, _ = answer_mention(loaded, settings, mention=mention, pack=_StubPack(),
                                   gateway=gw, llm=_Llm())
        assert first.status == "executed" and second.status == "deduplicated"
        assert count["n"] == 1
    finally:
        gw.close()


# --- dispatch + schedule (S3) ---


def test_dispatch_single_transport_is_passthrough(tmp_path, monkeypatch):
    from my_crew.runtime import inbox_dispatch

    marker = {"status": "replied_1", "replied": 1, "cost_usd": 0.1, "delivered": True}
    monkeypatch.setattr("my_crew.runtime.inbox.run_inbox", lambda ld, st: marker)
    loaded = _loaded(tmp_path, telegram=None, inbox={"channel": "C_IN", "poll_minutes": 2})
    assert inbox_dispatch.run_all_inboxes(loaded, loaded.settings) is marker


def test_dispatch_merges_both_and_survives_one_crash(tmp_path, monkeypatch):
    from my_crew.runtime import inbox_dispatch

    def _slack_boom(ld, st):
        raise RuntimeError("slack transport down")

    monkeypatch.setattr("my_crew.runtime.inbox.run_inbox", _slack_boom)
    monkeypatch.setattr(
        "my_crew.runtime.telegram_inbox.run_telegram_inbox",
        lambda ld, st: {"status": "replied_2", "replied": 2, "cost_usd": 0.2,
                        "delivered": True},
    )
    loaded = _loaded(tmp_path, telegram={"bot_token_env": _TOKEN_ENV, "chat_ids": ["111"]},
                     inbox={"channel": "C_IN", "poll_minutes": 5})
    out = inbox_dispatch.run_all_inboxes(loaded, loaded.settings)
    assert out["status"] == "slack=error;telegram=replied_2"
    assert out["replied"] == 2 and out["delivered"] is True


def test_dispatch_without_any_transport_raises(tmp_path):
    from my_crew.runtime.inbox_dispatch import run_all_inboxes

    loaded = _loaded(tmp_path, telegram=None, inbox=None)
    with pytest.raises(RuntimeError, match="no inbox"):
        run_all_inboxes(loaded, loaded.settings)


def test_schedule_folds_in_fastest_transport(tmp_path):
    from my_crew.runtime.service import _effective_schedule

    both = _loaded(tmp_path, telegram={"bot_token_env": _TOKEN_ENV, "chat_ids": ["111"],
                                       "poll_minutes": 7},
                   inbox={"channel": "C_IN", "poll_minutes": 3})
    schedule, reports = _effective_schedule(both)
    assert schedule["inbox"] == "*/3 * * * *" and "inbox" in reports

    tg_only = _loaded(tmp_path, telegram={"bot_token_env": _TOKEN_ENV, "chat_ids": ["111"],
                                          "poll_minutes": 7})
    schedule, reports = _effective_schedule(tg_only)
    assert schedule["inbox"] == "*/7 * * * *"

    none = _loaded(tmp_path, telegram=None)
    schedule, reports = _effective_schedule(none)
    assert "inbox" not in schedule and "inbox" not in reports


# --- channel registry (S4) ---


def test_report_delivers_to_every_allowlisted_chat(tmp_path, monkeypatch):
    from my_crew.agent.channel_registry import deliver_extra_channels, resolve_channels

    monkeypatch.setenv(_TOKEN_ENV, "tok")
    sent = []
    monkeypatch.setattr(
        "my_crew.actions.telegram_write.api_call",
        lambda t, m, p=None: sent.append(p) or {"message_id": len(sent)},
    )
    config = _config({"bot_token_env": _TOKEN_ENV, "chat_ids": ["111", "222"]})
    assert resolve_channels(config) == ("telegram",)

    settings = build_settings_from_dict(
        {"openrouter_api_key": "k", "data_dir": tmp_path, "dry_run": False}
    )
    gw = ActionGateway(settings, external_channels=frozenset())
    try:
        results = deliver_extra_channels(
            "nội dung báo cáo", "Báo cáo ngày", gateway=gw, config=config,
            report_date="daily-2026-07-02", audience="internal",
        )
        assert [(label, r.status) for label, r in results] == [
            ("telegram:111", "executed"), ("telegram:222", "executed"),
        ]
        assert {p["chat_id"] for p in sent} == {"111", "222"}
        assert all("Báo cáo ngày" in p["text"] for p in sent)
    finally:
        gw.close()


def test_one_failing_chat_does_not_eat_the_others_report(tmp_path, monkeypatch):
    from my_crew.agent.channel_registry import deliver_extra_channels

    monkeypatch.setenv(_TOKEN_ENV, "tok")
    sent = []

    def _api(token, method, payload=None):
        if payload["chat_id"] == "111":
            raise RuntimeError("telegram API sendMessage failed: 403 blocked by user")
        sent.append(payload)
        return {"message_id": 1}

    monkeypatch.setattr("my_crew.actions.telegram_write.api_call", _api)
    config = _config({"bot_token_env": _TOKEN_ENV, "chat_ids": ["111", "222"]})
    settings = build_settings_from_dict(
        {"openrouter_api_key": "k", "data_dir": tmp_path, "dry_run": False}
    )
    gw = ActionGateway(settings, external_channels=frozenset())
    try:
        results = deliver_extra_channels(
            "nội dung", "Báo cáo", gateway=gw, config=config,
            report_date="daily-2026-07-03", audience="internal",
        )
        assert [(label, r.status) for label, r in results] == [("telegram:222", "executed")]
        assert sent[0]["chat_id"] == "222"  # chat 111 failed, 222 still got the report
    finally:
        gw.close()
