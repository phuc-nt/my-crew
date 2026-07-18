"""v8 M23 (review HIGH): the inbox gateways MUST carry the agent's auto_approve config, else
chat-command auto-approve is dead in the production runtime (telegram_inbox / inbox build the
gateway that qa_answer.answer_mention uses). This locks the telegram wiring so it can't regress.
"""

from __future__ import annotations

from types import SimpleNamespace


def _loaded(auto_approve):
    telegram = SimpleNamespace(bot_token_env="X", chat_ids=("555",), poll_minutes=1,
                               ops_operator_id="555")
    config = SimpleNamespace(telegram=telegram, slack_external_channels=frozenset(),
                             slack_report_channel="C1")
    return SimpleNamespace(profile_id="pm", domain="pm", config=config, auto_approve=auto_approve)


def test_telegram_inbox_gateway_gets_auto_approve(monkeypatch, tmp_path):
    from my_crew.runtime import telegram_inbox

    captured = {}

    class _FakeGateway:
        def __init__(self, settings, **kw):
            captured.update(kw)

        def close(self):
            pass

    # One message so the poll reaches the gateway construction, then answer_mention is stubbed.
    msg = {"transport": "telegram", "user": "555", "channel": "555", "text": "hi", "ts": "1",
           "update_id": 8}
    monkeypatch.setattr(
        "my_crew.tools.telegram_read.fetch_new_updates", lambda *a, **k: ([msg], [], 9)
    )
    monkeypatch.setattr("my_crew.runtime.telegram_inbox.load_offset", lambda d: 1)
    monkeypatch.setattr("my_crew.runtime.telegram_inbox.save_offset", lambda d, o: None)
    monkeypatch.setattr("my_crew.runtime.telegram_inbox._is_for_agent", lambda m, pid: True)
    monkeypatch.setattr("my_crew.actions.action_gateway.ActionGateway", _FakeGateway)
    monkeypatch.setattr("my_crew.packs.registry.PackRegistry.load",
                        lambda self, dom: SimpleNamespace(allowlist=None))
    monkeypatch.setattr(
        "my_crew.agent.qa_answer.answer_mention",
        lambda *a, **k: (SimpleNamespace(status="executed", summary="ok"), 0.0),
    )

    auto = {"actions": {"slack_post": {"enabled": True, "max_per_day": 5}}}
    telegram_inbox.run_telegram_inbox(_loaded(auto), SimpleNamespace(data_dir=str(tmp_path),
                                                                     write_disabled=False))
    assert captured.get("auto_approve") == auto  # the config reached the gateway


def test_slack_inbox_gateway_gets_auto_approve(monkeypatch, tmp_path):
    from my_crew.runtime import inbox

    captured = {}

    class _FakeGateway:
        def __init__(self, settings, **kw):
            captured.update(kw)

        def close(self):
            pass

    loaded = _loaded({"actions": {"slack_post": {"enabled": True, "max_per_day": 5}}})
    loaded.inbox = {"channel": "C1", "poll_minutes": 5}
    loaded.config.slack_server = SimpleNamespace()
    mention = {"transport": "slack", "user": "U1", "channel": "C1", "text": "hi", "ts": "2"}
    monkeypatch.setattr("my_crew.runtime.inbox.load_watermark", lambda d: "1")
    monkeypatch.setattr("my_crew.runtime.inbox.save_watermark", lambda d, ts: None)
    monkeypatch.setattr(
        "my_crew.runtime.inbox.fetch_new_mentions", lambda *a, **k: ([mention], "2")
    )
    monkeypatch.setattr("my_crew.actions.action_gateway.ActionGateway", _FakeGateway)
    monkeypatch.setattr("my_crew.packs.registry.PackRegistry.load",
                        lambda self, dom: SimpleNamespace(allowlist=None))
    monkeypatch.setattr("my_crew.agent.qa_answer.answer_mention",
                        lambda *a, **k: (SimpleNamespace(status="executed", summary="ok"), 0.0))

    inbox.run_inbox(loaded, SimpleNamespace(data_dir=str(tmp_path), write_disabled=False))
    assert captured.get("auto_approve") == loaded.auto_approve
