"""v5 M12: chat-command qua Lớp B. Offline (LLM + MCP stubbed).

Load-bearing properties:

- Chat NEVER executes: a valid command becomes a PENDING approval (gateway forced
  Lớp B) — nothing runs before a human approves; approve dispatches for real.
- Structural safety: malformed classifier output ⇒ question (never an action);
  args are schema-validated in code; the catalog is validated at pack load (a
  red-line tool cannot even be declared); Lớp A still wins inside
  `enqueue_for_approval`.
- Re-poll cannot double-enqueue (mention-ts marker in the approval reason).
- A pack without a catalog ⇒ M11 Q&A behavior byte-identical.
"""

from __future__ import annotations

import pytest

from src.actions.action_gateway import ActionGateway
from src.agent.chat_command import classify_intent, maybe_handle_command, validate_args
from src.config.config_builders import build_reporting_config_from_dict, build_settings_from_dict
from src.packs.registry import PackRegistry, _load_commands
from src.profile.loader import LoadedProfile


def _config():
    return build_reporting_config_from_dict(
        {"jira_project_key": "SCRUM", "github_repo": "o/r", "slack_report_channel": "C_REP",
         "slack_stakeholder_channel": "", "slack_external_channels": ""}
    )


def _loaded(tmp_path):
    settings = build_settings_from_dict(
        {"openrouter_api_key": "k", "data_dir": tmp_path, "dry_run": False, "trust_mode": "guarded"}
    )
    return LoadedProfile(
        profile_id="acme", name="Acme", enabled=True, settings=settings, config=_config(),
        soul="", project="", memory="", schedule={}, reports=("daily",), domain="pm",
        inbox={"channel": "C_IN", "poll_minutes": 2},
    )


class _FakeLlm:
    def __init__(self, content):
        self._content = content

    def complete(self, messages):
        return type("R", (), {"content": self._content, "cost_usd": 0.0002})()


def _pm_pack():
    return PackRegistry().load("pm")


def _mention(ts="42.1", text="@acme tạo ticket cho bug login"):
    return {"ts": ts, "text": text, "channel": "C_IN", "user": "U1"}


# --- catalog load-time validation ---


def test_pm_pack_ships_create_issue_catalog():
    commands = _pm_pack().commands
    assert set(commands) == {"create_issue"}
    assert commands["create_issue"]["server"] == "jira"


def test_catalog_with_forbidden_tool_is_rejected_at_load(tmp_path, monkeypatch):
    # A destructive tool (Lớp A) and a non-allowlisted server both fail LOUDLY.
    for bad in (
        {"server": "slack", "tool": "delete_message"},
        {"server": "filesystem", "tool": "write_file"},
    ):
        module = type("M", (), {"COMMANDS": {"boom": {**bad, "description": "x"}}})
        monkeypatch.setattr(
            "src.packs.registry._load_pack_module", lambda d, m, _mod=module: _mod
        )
        monkeypatch.setattr(
            "src.packs.registry.pack_dir",
            lambda d: tmp_path,  # commands.py existence check
        )
        (tmp_path / "commands.py").write_text("", encoding="utf-8")
        with pytest.raises(RuntimeError, match="forbidden tool"):
            _load_commands("pm", {"slack": ("post_message",)})


def test_catalog_noncallable_build_args_rejected_at_load(tmp_path, monkeypatch):
    module = type("M", (), {"COMMANDS": {"c": {
        "description": "x", "server": "slack", "tool": "post_message",
        "build_args": "not-callable",
    }}})
    monkeypatch.setattr("src.packs.registry._load_pack_module", lambda d, m: module)
    monkeypatch.setattr("src.packs.registry.pack_dir", lambda d: tmp_path)
    (tmp_path / "commands.py").write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="build_args must be callable"):
        _load_commands("pm", {"slack": ("post_message",)})


def test_catalog_empty_commands_export_rejected(tmp_path, monkeypatch):
    module = type("M", (), {"COMMANDS": {}})
    monkeypatch.setattr("src.packs.registry._load_pack_module", lambda d, m: module)
    monkeypatch.setattr("src.packs.registry.pack_dir", lambda d: tmp_path)
    (tmp_path / "commands.py").write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="exports no COMMANDS"):
        _load_commands("pm", {})


def test_classifier_reraises_infra_errors():
    # A provider outage must NOT be misread as "this was a question" — the inbox
    # holds its watermark on these and retries the mention (review M1).
    from src.llm.fallback_policy import ProviderCallError

    class _DownLlm:
        def complete(self, messages):
            raise ProviderCallError("all models down")

    with pytest.raises(ProviderCallError):
        classify_intent(_DownLlm(), "msg", _pm_pack().commands)


# --- intent classification (safe default) ---


@pytest.mark.parametrize("garbage", ["not json", '["list"]', '{"intent": "command"', ""])
def test_classifier_garbage_falls_back_to_question(garbage):
    out = classify_intent(_FakeLlm(garbage), "msg", _pm_pack().commands)
    assert out["intent"] == "question"


def test_classifier_parses_command_and_strips_fences():
    raw = ('```json\n{"intent":"command","command_id":"create_issue",'
           '"args":{"summary":"Bug X"}}\n```')
    out = classify_intent(_FakeLlm(raw), "msg", _pm_pack().commands)
    assert out["intent"] == "command" and out["args"] == {"summary": "Bug X"}


# --- args validation ---


def test_validate_args_rules():
    spec = _pm_pack().commands["create_issue"]
    clean, err = validate_args(spec, {"summary": "  Bug X  "})
    assert err is None and clean == {"summary": "Bug X"}
    assert validate_args(spec, {"summary": ""})[1].startswith("thiếu field")
    assert validate_args(spec, {"summary": "x", "hack": "y"})[1].startswith("field không")
    assert validate_args(spec, {"summary": "x" * 201})[1].startswith("field summary dài")
    assert validate_args(spec, "notdict")[1] == "args phải là một object"
    assert validate_args(spec, {"summary": 42})[1] == "field summary phải là chuỗi"


# --- the forced Lớp B flow ---


def _gw(loaded):
    return ActionGateway(
        loaded.settings, external_channels=frozenset(),
        mcp_allowlist=_pm_pack().allowlist,
    )


def test_valid_command_enqueues_and_nothing_executes(tmp_path):
    loaded = _loaded(tmp_path)
    gw = _gw(loaded)
    try:
        llm = _FakeLlm('{"intent":"command","command_id":"create_issue",'
                       '"args":{"summary":"Bug login"}}')
        reply, cost = maybe_handle_command(
            loaded=loaded, config=loaded.config, mention=_mention(),
            pack=_pm_pack(), gateway=gw, llm=llm,
        )
        pending = gw.pending_approvals()
        assert len(pending) == 1
        action = pending[0].action
        assert action["server"] == "jira" and action["tool"] == "createIssue"
        assert action["args"] == {"projectKey": "SCRUM", "summary": "Bug login"}
        assert f"#{pending[0].id}" in reply and "chờ duyệt" in reply
        assert cost == 0.0002
    finally:
        gw.close()


def test_same_mention_ts_does_not_double_enqueue(tmp_path):
    loaded = _loaded(tmp_path)
    gw = _gw(loaded)
    try:
        llm = _FakeLlm('{"intent":"command","command_id":"create_issue",'
                       '"args":{"summary":"Bug"}}')
        kwargs = dict(loaded=loaded, config=loaded.config, mention=_mention(ts="7.7"),
                      pack=_pm_pack(), gateway=gw, llm=llm)
        maybe_handle_command(**kwargs)
        reply2, _ = maybe_handle_command(**kwargs)
        assert len(gw.pending_approvals()) == 1
        assert "đã ở hàng chờ duyệt" in reply2
    finally:
        gw.close()


def test_question_returns_none_and_unsupported_lists_catalog(tmp_path):
    loaded = _loaded(tmp_path)
    gw = _gw(loaded)
    try:
        assert maybe_handle_command(
            loaded=loaded, config=loaded.config, mention=_mention(),
            pack=_pm_pack(), gateway=gw, llm=_FakeLlm('{"intent":"question"}'),
        ) is None
        reply, _ = maybe_handle_command(
            loaded=loaded, config=loaded.config, mention=_mention(),
            pack=_pm_pack(), gateway=gw, llm=_FakeLlm('{"intent":"unsupported"}'),
        )
        assert "create_issue" in reply and not gw.pending_approvals()
    finally:
        gw.close()


def test_invalid_args_reply_and_no_enqueue(tmp_path):
    loaded = _loaded(tmp_path)
    gw = _gw(loaded)
    try:
        reply, _ = maybe_handle_command(
            loaded=loaded, config=loaded.config, mention=_mention(),
            pack=_pm_pack(), gateway=gw,
            llm=_FakeLlm('{"intent":"command","command_id":"create_issue","args":{}}'),
        )
        assert "thiếu field bắt buộc" in reply and not gw.pending_approvals()
    finally:
        gw.close()


def test_pack_without_catalog_skips_classifier_entirely(tmp_path):
    loaded = _loaded(tmp_path)

    class _NoCatalogPack:
        commands = {}

    class _Boom:
        def complete(self, messages):  # classifier must NOT be called
            raise AssertionError("LLM called for a catalog-less pack")

    assert maybe_handle_command(
        loaded=loaded, config=loaded.config, mention=_mention(),
        pack=_NoCatalogPack(), gateway=None, llm=_Boom(),
    ) is None


# --- gateway.enqueue_for_approval red line ---


def test_enqueue_for_approval_refuses_hard_denied_action(tmp_path):
    loaded = _loaded(tmp_path)
    gw = _gw(loaded)
    try:
        result = gw.enqueue_for_approval(
            {"type": "mcp_tool", "server": "slack", "tool": "delete_message", "args": {}},
            reason="chat-command thử xóa",
        )
        assert result.status == "skipped" and "hard-denied" in result.summary
        assert not gw.pending_approvals()  # a red-line action is never even queued
    finally:
        gw.close()


# --- approve → jira dispatch ---


def test_approve_dispatches_jira_create_issue(tmp_path, monkeypatch):
    from src.actions.approved_dispatch import dispatch_approved_action

    loaded = _loaded(tmp_path)
    gw = _gw(loaded)
    calls = {}

    def fake_call_tool(server, tool, args):
        calls.update(server=server, tool=tool, args=args)
        return {"key": "SCRUM-99"}

    monkeypatch.setattr("src.actions.jira_write.call_tool", fake_call_tool)
    try:
        queued = gw.enqueue_for_approval(
            {"type": "mcp_tool", "server": "jira", "tool": "createIssue",
             "args": {"projectKey": "SCRUM", "summary": "Bug"}},
            reason="chat-command 'create_issue' (chat-command ts=1.1)",
        )
        result = gw.approve(
            queued.approval_id,
            handler=lambda a: dispatch_approved_action(a, loaded.config),
        )
        assert result.status == "executed" and "SCRUM-99" in result.summary
        assert calls["tool"] == "createIssue" and calls["args"]["projectKey"] == "SCRUM"
    finally:
        gw.close()


# --- autonomous trust mode: chat runs immediately for any reachable sender (v30) ---


def _loaded_autonomous(tmp_path, *, dry_run=False):
    settings = build_settings_from_dict(
        {"openrouter_api_key": "k", "data_dir": tmp_path, "dry_run": dry_run,
         "trust_mode": "autonomous"}
    )
    return LoadedProfile(
        profile_id="acme", name="Acme", enabled=True, settings=settings, config=_config(),
        soul="", project="", memory="", schedule={}, reports=("daily",), domain="pm",
        inbox={"channel": "C_IN", "poll_minutes": 2},
    )


def test_autonomous_command_runs_now_and_names_the_mode(tmp_path, monkeypatch):
    loaded = _loaded_autonomous(tmp_path)
    gw = _gw(loaded)
    calls = []
    monkeypatch.setattr(
        "src.actions.approved_dispatch.dispatch_approved_action",
        lambda a, cfg: calls.append(a) or "jira createIssue -> SCRUM-9",
    )
    try:
        llm = _FakeLlm('{"intent":"command","command_id":"create_issue",'
                       '"args":{"summary":"Bug login"}}')
        reply, _ = maybe_handle_command(
            loaded=loaded, config=loaded.config, mention=_mention(),
            pack=_pm_pack(), gateway=gw, llm=llm,
        )
        assert "chế độ tự chủ" in reply and "✅" in reply
        assert len(calls) == 1
        assert gw.pending_approvals() == []
    finally:
        gw.close()


def test_autonomous_duplicate_command_reports_dedup_not_refusal(tmp_path, monkeypatch):
    loaded = _loaded_autonomous(tmp_path)
    gw = _gw(loaded)
    monkeypatch.setattr(
        "src.actions.approved_dispatch.dispatch_approved_action", lambda a, cfg: "ok",
    )
    try:
        llm = _FakeLlm('{"intent":"command","command_id":"create_issue",'
                       '"args":{"summary":"Bug"}}')
        kwargs = dict(loaded=loaded, config=loaded.config, pack=_pm_pack(), gateway=gw, llm=llm)
        maybe_handle_command(mention=_mention(ts="1.1"), **kwargs)
        reply2, _ = maybe_handle_command(mention=_mention(ts="2.2"), **kwargs)
        assert "chống chạy đúp" in reply2
        assert "từ chối" not in reply2
    finally:
        gw.close()


def test_autonomous_dry_run_reply_names_dry_run_not_refusal(tmp_path):
    loaded = _loaded_autonomous(tmp_path, dry_run=True)
    gw = _gw(loaded)
    try:
        llm = _FakeLlm('{"intent":"command","command_id":"create_issue",'
                       '"args":{"summary":"Bug"}}')
        reply, _ = maybe_handle_command(
            loaded=loaded, config=loaded.config, mention=_mention(),
            pack=_pm_pack(), gateway=gw, llm=llm,
        )
        assert "dry-run" in reply
        assert "từ chối" not in reply
    finally:
        gw.close()
