"""v3 M11: ask-agent Slack inbox — config, poll/watermark, QA answer, wiring.

Offline (Slack MCP + LLM stubbed). Load-bearing properties:

- `inbox:` absent ⇒ None everywhere ⇒ scheduler/worker behavior byte-identical.
- EXTERNAL channel rejected at load (persona/memory must not reach stakeholders).
- Bootstrap poll answers NOTHING (no backlog flood); watermark advances only over
  processed messages; per-poll reply cap holds.
- The reply is delivered through the REAL Action Gateway: dedup by mention ts (a
  re-poll can never double-reply), post_message allowlisted, thread_ts set, and the
  gateway remains the only write path (a poison mention is skipped, not fatal).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from my_crew.config.config_builders import (
    build_reporting_config_from_dict,
    build_settings_from_dict,
)
from my_crew.profile.loader import LoadedProfile, _parse_inbox
from my_crew.runtime import inbox as inbox_mod
from my_crew.runtime.service import _effective_schedule


def _config(**over):
    d = {"jira_project_key": "X", "github_repo": "o/r", "slack_report_channel": "C_REP",
         "slack_stakeholder_channel": "", "slack_external_channels": ""}
    d.update(over)
    return build_reporting_config_from_dict(d)


def _loaded(tmp_path, *, inbox=None, reports=("daily",), domain="pm", soul="", memory=""):
    settings = build_settings_from_dict(
        {"openrouter_api_key": "k", "data_dir": tmp_path, "dry_run": True}
    )
    return LoadedProfile(
        profile_id="acme", name="Acme", enabled=True, settings=settings, config=_config(),
        soul=soul, project="", memory=memory, schedule={"daily": "0 9 * * *"},
        reports=tuple(reports), domain=domain, inbox=inbox,
    )


# --- config parse (S1) ---


def test_parse_inbox_absent_is_none():
    assert _parse_inbox(None, _config()) is None
    assert _parse_inbox({}, _config()) is None


def test_parse_inbox_happy_and_defaults():
    parsed = _parse_inbox({"channel": "C_IN"}, _config())
    assert parsed == {"channel": "C_IN", "poll_minutes": 5}
    parsed = _parse_inbox({"channel": "C_IN", "poll_minutes": 2}, _config())
    assert parsed["poll_minutes"] == 2


@pytest.mark.parametrize(
    "raw", [{"poll_minutes": 5}, {"channel": ""}, {"channel": "C", "poll_minutes": 0},
            {"channel": "C", "poll_minutes": "x"}, "notamap"],
)
def test_parse_inbox_bad_shapes_raise(raw):
    with pytest.raises(RuntimeError):
        _parse_inbox(raw, _config())


def test_parse_inbox_rejects_external_channel():
    cfg = _config(slack_stakeholder_channel="C_EXT", slack_external_channels="C_EXT")
    with pytest.raises(RuntimeError, match="internal-only"):
        _parse_inbox({"channel": "C_EXT"}, cfg)


# --- scheduler wiring (S4) ---


def test_effective_schedule_without_inbox_is_identical(tmp_path):
    loaded = _loaded(tmp_path)
    schedule, reports = _effective_schedule(loaded)
    assert schedule is loaded.schedule and reports is loaded.reports


def test_effective_schedule_synthesizes_inbox_kind(tmp_path):
    loaded = _loaded(tmp_path, inbox={"channel": "C_IN", "poll_minutes": 3})
    schedule, reports = _effective_schedule(loaded)
    assert schedule["inbox"] == "*/3 * * * *"
    assert "inbox" in reports and "daily" in schedule  # original entries kept


# --- poll + watermark (S2) ---


def _mention(ts, text):
    return {"ts": ts, "text": text, "channel": "C_IN", "user": "U1"}


def test_fetch_filters_by_watermark_and_phrase(monkeypatch):
    calls = {}

    def fake_call_tool(server, tool, args):
        calls[tool] = args
        if tool == "list_workspace_channels":
            return {"channels": [{"id": "C_IN", "name": "report"}]}
        return {"messages": [
            _mention("100.1", "@acme cÅ©"), _mention("200.2", "@acme mới nhé"),
            _mention("300.3", "không nhắc tên"),
        ]}

    monkeypatch.setattr(inbox_mod, "call_tool", fake_call_tool)
    fresh, newest = inbox_mod.fetch_new_mentions(
        None, channel_id="C_IN", agent_id="acme", last_ts="150"
    )
    assert [m["ts"] for m in fresh] == ["200.2"]  # >watermark AND contains @acme
    assert newest == "300.3"
    assert calls["search_messages"]["query"].startswith('in:report "@acme"')


def test_fetch_unknown_channel_raises(monkeypatch):
    monkeypatch.setattr(
        inbox_mod, "call_tool",
        lambda s, t, a: {"channels": [{"id": "C_OTHER", "name": "x"}]},
    )
    with pytest.raises(RuntimeError, match="not found"):
        inbox_mod.fetch_new_mentions(None, channel_id="C_IN", agent_id="a", last_ts="1")


def test_channel_name_retries_with_bypass_cache_before_raising(monkeypatch):
    """v11 P3 (F7): P1's 15-min cache can hide a new/renamed channel. The first
    (possibly cached) list misses it; retry ONCE with bypass_cache=True before the
    resolver gives up — a genuinely absent channel still raises after both tries."""
    calls: list[dict] = []

    def fake_call_tool(server, tool, args):
        calls.append(args)
        if len(calls) == 1:
            return {"channels": [{"id": "C_OTHER", "name": "x"}]}  # miss (cached)
        return {"channels": [{"id": "C_IN", "name": "fresh-channel"}]}  # found on retry

    monkeypatch.setattr(inbox_mod, "call_tool", fake_call_tool)
    name = inbox_mod._channel_name(None, "C_IN")

    assert name == "fresh-channel"
    assert len(calls) == 2
    assert calls[0].get("bypass_cache") is not True
    assert calls[1]["bypass_cache"] is True


def test_channel_name_raises_after_retry_still_misses(monkeypatch):
    calls: list[dict] = []

    def fake_call_tool(server, tool, args):
        calls.append(args)
        return {"channels": [{"id": "C_OTHER", "name": "x"}]}  # never found

    monkeypatch.setattr(inbox_mod, "call_tool", fake_call_tool)
    with pytest.raises(RuntimeError, match="not found"):
        inbox_mod._channel_name(None, "C_IN")
    assert len(calls) == 2  # both the plain lookup AND the bypass_cache retry happened
    assert calls[1]["bypass_cache"] is True


def test_bootstrap_answers_nothing_and_sets_watermark(tmp_path, monkeypatch):
    loaded = _loaded(tmp_path, inbox={"channel": "C_IN", "poll_minutes": 2})
    monkeypatch.setattr(
        inbox_mod, "fetch_new_mentions", lambda *a, **k: ([], "555.5")
    )
    result = inbox_mod.run_inbox(loaded, loaded.settings)
    assert result == {"status": "bootstrapped", "replied": 0, "cost_usd": None,
                      "delivered": False}
    assert inbox_mod.load_watermark(Path(tmp_path)) == "555.5"


def test_run_inbox_caps_replies_and_advances_watermark(tmp_path, monkeypatch):
    loaded = _loaded(tmp_path, inbox={"channel": "C_IN", "poll_minutes": 2})
    inbox_mod.save_watermark(Path(tmp_path), "100")
    mentions = [_mention(f"{i}00.1", f"@acme q{i}") for i in range(2, 7)]  # 5 mentions
    monkeypatch.setattr(inbox_mod, "fetch_new_mentions", lambda *a, **k: (mentions, "600.1"))
    answered = []

    def fake_answer(loaded_, settings_, *, mention, pack=None, gateway=None):
        answered.append(mention["ts"])
        return type("R", (), {"status": "executed", "summary": "ok"})(), 0.001

    monkeypatch.setattr("my_crew.agent.qa_answer.answer_mention", fake_answer)
    result = inbox_mod.run_inbox(loaded, loaded.settings)
    assert result["replied"] == 3 and len(answered) == 3  # per-poll cap
    # Watermark = last PROCESSED ts, so the 2 remaining are picked up next poll.
    assert inbox_mod.load_watermark(Path(tmp_path)) == "400.1"
    assert result["cost_usd"] == pytest.approx(0.003)


def test_run_inbox_infra_failure_holds_watermark(tmp_path, monkeypatch):
    from my_crew.llm.fallback_policy import ProviderCallError

    loaded = _loaded(tmp_path, inbox={"channel": "C_IN", "poll_minutes": 2})
    inbox_mod.save_watermark(Path(tmp_path), "100")
    mentions = [_mention("200.1", "@acme q1"), _mention("300.1", "@acme q2")]
    monkeypatch.setattr(inbox_mod, "fetch_new_mentions", lambda *a, **k: (mentions, None))

    def fake_answer(loaded_, settings_, *, mention, pack=None, gateway=None):
        raise ProviderCallError("all models down")

    monkeypatch.setattr("my_crew.agent.qa_answer.answer_mention", fake_answer)
    result = inbox_mod.run_inbox(loaded, loaded.settings)
    assert result["replied"] == 0
    # Watermark HELD: the provider outage is not the question's fault — retry next poll.
    assert inbox_mod.load_watermark(Path(tmp_path)) == "100"


def test_run_inbox_kill_switch_skips_poll_without_llm_burn(tmp_path, monkeypatch):
    loaded = _loaded(tmp_path, inbox={"channel": "C_IN", "poll_minutes": 2})
    settings = build_settings_from_dict(
        {"openrouter_api_key": "k", "data_dir": tmp_path, "write_disabled": True}
    )
    inbox_mod.save_watermark(Path(tmp_path), "100")
    monkeypatch.setattr(
        inbox_mod, "fetch_new_mentions",
        lambda *a, **k: ([_mention("200.1", "@acme q")], None),
    )
    result = inbox_mod.run_inbox(loaded, settings)
    assert result["status"] == "writes_disabled" and result["replied"] == 0
    assert inbox_mod.load_watermark(Path(tmp_path)) == "100"  # held


def test_fetch_query_is_time_bounded_and_case_insensitive(monkeypatch):
    calls = {}

    def fake_call_tool(server, tool, args):
        calls[tool] = args
        if tool == "list_workspace_channels":
            return {"channels": [{"id": "C_IN", "name": "report"}]}
        return {"messages": [_mention("200.2", "@Acme viết HOA vẫn là hỏi")]}

    monkeypatch.setattr(inbox_mod, "call_tool", fake_call_tool)
    fresh, _ = inbox_mod.fetch_new_mentions(
        None, channel_id="C_IN", agent_id="acme", last_ts="150"
    )
    assert [m["ts"] for m in fresh] == ["200.2"]  # case-insensitive phrase match
    assert "after:" in calls["search_messages"]["query"]  # bounded window (M1)


def test_run_inbox_poison_mention_skipped_not_fatal(tmp_path, monkeypatch):
    loaded = _loaded(tmp_path, inbox={"channel": "C_IN", "poll_minutes": 2})
    inbox_mod.save_watermark(Path(tmp_path), "100")
    mentions = [_mention("200.1", "@acme boom"), _mention("300.1", "@acme ok")]
    monkeypatch.setattr(inbox_mod, "fetch_new_mentions", lambda *a, **k: (mentions, None))

    def fake_answer(loaded_, settings_, *, mention, pack=None, gateway=None):
        if mention["ts"] == "200.1":
            raise RuntimeError("provider down")
        return type("R", (), {"status": "executed", "summary": "ok"})(), None

    monkeypatch.setattr("my_crew.agent.qa_answer.answer_mention", fake_answer)
    result = inbox_mod.run_inbox(loaded, loaded.settings)
    assert result["replied"] == 1
    assert inbox_mod.load_watermark(Path(tmp_path)) == "300.1"  # moved past the poison


# --- QA answer through the real gateway (S3 + red line) ---


class _FakePack:
    def __init__(self):
        self.report_kinds = {"daily": lambda **k: None}
        self.prompts = {}
        self.allowlist = {"slack": ("post_message",)}
        self.tools = type(
            "T", (), {"read": staticmethod(lambda kind, config, settings: {"open": 2})}
        )()


class _FakeLlm:
    def __init__(self, content="Có 2 việc đang mở."):
        self._content = content
        self.messages = None

    def complete(self, messages):
        self.messages = messages
        return type("R", (), {"content": self._content, "cost_usd": 0.0005})()


def test_answer_mention_delivers_threaded_reply_via_gateway(tmp_path):
    from my_crew.actions.action_gateway import ActionGateway
    from my_crew.agent.qa_answer import answer_mention

    loaded = _loaded(
        tmp_path, inbox={"channel": "C_IN", "poll_minutes": 2},
        soul="Bạn là PM.", memory="SECRET-MEM",
    )
    settings = build_settings_from_dict(  # dry_run FALSE + fake handler = executed path
        {"openrouter_api_key": "k", "data_dir": tmp_path, "dry_run": False}
    )
    pack, llm = _FakePack(), _FakeLlm()
    gw = ActionGateway(settings, external_channels=frozenset(),
                       mcp_allowlist=pack.allowlist)
    posted = {}
    import my_crew.agent.qa_answer as qa

    def fake_handler_factory(server):
        def _h(action):
            posted.update(action["args"])
            return "posted"
        return _h

    orig = qa.make_slack_post_handler
    qa.make_slack_post_handler = fake_handler_factory
    try:
        mention = _mention("777.1", "@acme còn bao nhiêu việc?")
        outcome, cost = answer_mention(loaded, settings, mention=mention,
                                       pack=pack, gateway=gw, llm=llm)
        assert outcome.status == "executed" and cost == 0.0005
        assert posted["thread_ts"] == "777.1" and posted["channel"] == "C_IN"
        # Persona + internal context reached the prompt; question stays in user role.
        assert "Bạn là PM." in llm.messages[0]["content"]
        assert "SECRET-MEM" in llm.messages[1]["content"]
        assert "còn bao nhiêu việc" in llm.messages[1]["content"]
        # Reply must never contain the mention phrase (self-loop guard).
        assert "@acme" not in posted["text"]
        # DEDUP: answering the same mention again is refused by the gateway.
        outcome2, _ = answer_mention(loaded, settings, mention=mention,
                                     pack=pack, gateway=gw, llm=llm)
        assert outcome2.status == "deduplicated"
    finally:
        qa.make_slack_post_handler = orig
        gw.close()


def test_answer_mention_empty_llm_reply_raises(tmp_path):
    from my_crew.agent.qa_answer import answer_mention

    loaded = _loaded(tmp_path, inbox={"channel": "C_IN", "poll_minutes": 2})
    with pytest.raises(RuntimeError, match="empty"):
        answer_mention(loaded, loaded.settings, mention=_mention("1.1", "@acme ?"),
                       pack=_FakePack(), llm=_FakeLlm(content="  "))


def test_sanitize_reply_strips_mention_phrase_and_broadcasts():
    from my_crew.agent.qa_answer import sanitize_reply

    dirty = "Theo tôi @ACME rất bận. <!channel> chú ý: @acme sẽ trả lời."
    clean = sanitize_reply(dirty, "acme")
    assert "@acme" not in clean.lower()  # self-loop phrase gone, any case
    assert "<!channel>" not in clean
    assert "acme" in clean  # tên vẫn đọc được, chỉ mất ký tự @ trước tên


def test_answer_mention_posts_sanitized_text_even_when_llm_echoes(tmp_path):
    # The anti-loop guard must be structural: feed an LLM that DOES echo the phrase.
    import my_crew.agent.qa_answer as qa
    from my_crew.actions.action_gateway import ActionGateway
    from my_crew.agent.qa_answer import answer_mention

    loaded = _loaded(tmp_path, inbox={"channel": "C_IN", "poll_minutes": 2})
    settings = build_settings_from_dict(
        {"openrouter_api_key": "k", "data_dir": tmp_path, "dry_run": False}
    )
    pack = _FakePack()
    llm = _FakeLlm(content="@acme nghĩ rằng có 2 việc. Hỏi @ACME thêm nhé <!here>")
    gw = ActionGateway(settings, external_channels=frozenset(),
                       mcp_allowlist=pack.allowlist)
    posted = {}
    orig = qa.make_slack_post_handler
    qa.make_slack_post_handler = lambda server: (lambda a: posted.update(a["args"]) or "ok")
    try:
        answer_mention(loaded, settings, mention=_mention("9.1", "@acme ?"),
                       pack=pack, gateway=gw, llm=llm)
        assert "@acme" not in posted["text"].lower()
        assert "<!here>" not in posted["text"]
    finally:
        qa.make_slack_post_handler = orig
        gw.close()


def test_render_snapshot_bounded():
    from my_crew.agent.qa_answer import render_snapshot

    text = render_snapshot({"rows": ["x" * 100] * 200})
    assert len(text) < 6200 and "cắt bớt" in text


# --- worker wiring (S4) ---


def test_worker_inbox_kind_runs_poll_and_records_event(tmp_path, monkeypatch):
    from my_crew.runtime import worker

    monkeypatch.setattr("my_crew.runtime.agent_paths.DATA_DIR", tmp_path / ".data")
    loaded = _loaded(tmp_path, inbox={"channel": "C_IN", "poll_minutes": 2})
    monkeypatch.setattr(worker, "load_profile", lambda aid, data_dir=None: loaded)
    monkeypatch.setattr(worker, "migrate_legacy_data_dir", lambda: None)
    monkeypatch.setattr(
        "my_crew.runtime.inbox.run_inbox",
        lambda ld, st: {"status": "replied_1", "replied": 1, "cost_usd": 0.001,
                        "delivered": True},
    )
    rc = worker.main(["--agent-id", "acme", "--report", "inbox"])
    assert rc == 0
    runs = (tmp_path / ".data" / "agents" / "acme" / "runs.jsonl").read_text()
    event = json.loads(runs.strip().splitlines()[-1])
    assert event["kind"] == "inbox" and event["status"] == "replied_1"
    assert event["delivered"] is True
