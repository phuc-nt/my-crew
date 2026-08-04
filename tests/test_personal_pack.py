"""v57: personal-pack — thư ký riêng, kênh Telegram DM. Offline.

Load-bearing properties:

- Pack assembly: discovery thấy `personal`; 2 kind briefing + weekly-review; allowlist
  RỖNG (thư ký không ghi MCP nào — default-DENY nguyên vẹn); prompts qa/briefing/weekly
  có mặt (qa-system là persona chat DM, seam qa_answer.py).
- ToolProvider: bối cảnh ngày (thuần code) + gws lịch/email (mock trong test; degrade
  per-source thành chuỗi nói-thật khi CLI lỗi — không bao giờ crash vòng trả lời).
- Graph briefing chạy offline end-to-end: không API key ⇒ fallback thuần code vẫn
  ship bản tin; dry-run delivery tính là giao; thiếu telegram ⇒ skip có tiếng,
  không crash; audience external ⇒ fail loud (bản tin mang trí nhớ cá nhân).
"""

from __future__ import annotations

import dataclasses

import pytest

from my_crew.config.config_builders import (
    build_reporting_config_from_dict,
    build_settings_from_dict,
)
from my_crew.config.telegram_config import TelegramConfig
from my_crew.packs.registry import PackRegistry, discover_domains

# --- pack assembly ---


def test_personal_pack_discovered_and_assembled():
    assert "personal" in discover_domains()
    pack = PackRegistry().load("personal")
    assert set(pack.report_kinds) == {"briefing", "weekly-review"}
    assert pack.allowlist == {}  # thư ký không ghi MCP nào — default-DENY nguyên vẹn
    assert "qa-system" in pack.prompts
    assert "briefing-system" in pack.prompts
    assert "weekly-review-system" in pack.prompts
    assert pack.tools is not None
    # 3b calendar + v58 email + v60 sửa/xoá lịch; v61: id English, giao việc đi qua
    # tầng ops orchestration (không còn lệnh M12 riêng); v65: nhắc hẹn giờ một lần.
    assert set(pack.commands) == {"create_event", "update_event", "delete_event",
                                  "send_email", "set_reminder", "cancel_reminder"}


def test_tool_provider_reads_day_context_plus_gws(monkeypatch):
    monkeypatch.setattr("my_crew.tools.gws_read.calendar_agenda", lambda: '{"events": []}')
    monkeypatch.setattr("my_crew.tools.gws_read.gmail_triage", lambda: '{"unread": 2}')
    pack = PackRegistry().load("personal")
    snapshot = pack.tools.read("briefing", None, None)
    assert snapshot["current_time"]  # ISO local time
    assert snapshot["weekday"].startswith(("Thứ", "Chủ"))
    assert snapshot["calendar_next_24h"] == '{"events": []}'
    assert snapshot["unread_email"] == '{"unread": 2}'


def test_tool_provider_degrades_per_source_on_gws_failure(monkeypatch):
    """CLI thiếu/OAuth hết hạn → snapshot vẫn ra, nguồn lỗi thành chuỗi nói-thật —
    thư ký trả lời 'chưa xem được' thay vì crash vòng chat/briefing."""
    from my_crew.tools.gws_read import GwsReadError

    def boom():
        raise GwsReadError("gws CLI chưa cài")

    monkeypatch.setattr("my_crew.tools.gws_read.calendar_agenda", boom)
    monkeypatch.setattr("my_crew.tools.gws_read.gmail_triage", lambda: '{"unread": 0}')
    pack = PackRegistry().load("personal")
    snapshot = pack.tools.read("briefing", None, None)
    assert snapshot["calendar_next_24h"].startswith("(chưa đọc được:")
    assert snapshot["unread_email"] == '{"unread": 0}'  # nguồn lành không bị vạ lây


# --- offline end-to-end graph run ---


class _FakeDayTools:
    """Provider giả cho graph tests — không chạm CLI gws thật (chậm + đọc data thật)."""

    def read(self, kind, config, settings):
        return {"current_time": "2026-08-03T07:00+07:00", "weekday": "Thứ Hai",
                "calendar_next_24h": "(chưa đọc được: test)",
                "unread_email": "(chưa đọc được: test)"}


def _config(with_telegram: bool):
    config = build_reporting_config_from_dict(
        {"jira_project_key": "X", "github_repo": "o/r", "slack_report_channel": "C_TK",
         "slack_stakeholder_channel": "", "slack_external_channels": ""}
    )
    if not with_telegram:
        return config
    telegram = TelegramConfig(
        bot_token_env="TK_TEST_BOT_TOKEN", chat_ids=("111",), ops_operator_id="111"
    )
    return dataclasses.replace(config, telegram=telegram)


def test_briefing_graph_offline_dry_run_delivers_to_telegram(tmp_path):
    pack = PackRegistry().load("personal")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": True})  # no API key
    graph = pack.report_kinds["briefing"](
        None, config=_config(True), settings=settings, tools=_FakeDayTools()
    )
    result = graph.invoke({})
    assert result["delivered"] is True  # dry-run delivery tính là giao
    assert result["delivery_summary"] == "telegram=dry_run"
    # Không API key ⇒ compose rơi về fallback thuần code — vẫn có ngày giờ, không bịa.
    assert "Hôm nay là" in result["report_text"]


def test_briefing_graph_without_telegram_skips_loudly(tmp_path):
    pack = PackRegistry().load("personal")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": True})
    graph = pack.report_kinds["briefing"](
        None, config=_config(False), settings=settings, tools=_FakeDayTools()
    )
    result = graph.invoke({})
    assert result["delivered"] is False
    assert result["delivery_summary"] == "telegram=not_configured"


def test_briefing_graph_rejects_external_audience(tmp_path):
    pack = PackRegistry().load("personal")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": True})
    with pytest.raises(ValueError, match="internal"):
        pack.report_kinds["briefing"](
            None, config=_config(True), settings=settings, audience="external",
            tools=_FakeDayTools(),
        )


def test_briefing_live_send_dedups_per_day_but_not_across_kinds(tmp_path, monkeypatch):
    """Non-dry-run qua gateway THẬT (api_call stub): lần 1 gửi, lần 2 CÙNG NGÀY bị dedup,
    nhưng weekly-review CÙNG NGÀY vẫn gửi (kind nằm trong dedup hint).

    Dry-run return trước tầng dedup nên test dry-run không bao giờ chạm hành vi này."""
    calls: list[dict] = []
    monkeypatch.setenv("TK_TEST_BOT_TOKEN", "test-token")
    monkeypatch.setattr(
        "my_crew.actions.telegram_write.api_call",
        lambda token, method, payload, **kw: calls.append(payload) or {"message_id": 7},
    )
    pack = PackRegistry().load("personal")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": False})
    config = _config(True)
    first = pack.report_kinds["briefing"](
        None, config=config, settings=settings, tools=_FakeDayTools()
    ).invoke({})
    second = pack.report_kinds["briefing"](
        None, config=config, settings=settings, tools=_FakeDayTools()
    ).invoke({})
    assert first["delivered"] is True
    assert first["delivery_summary"] == "telegram=executed"
    assert len(calls) == 1  # đúng 1 lần chạm Bot API
    assert second["delivered"] is False  # cùng ngày ⇒ dedup, không gửi lại
    assert second["delivery_summary"] == "telegram=deduplicated"
    assert len(calls) == 1
    weekly = pack.report_kinds["weekly-review"](
        None, config=config, settings=settings, tools=_FakeDayTools()
    ).invoke({})
    assert weekly["delivered"] is True  # kind khác ⇒ hint khác ⇒ không dedup chéo
    assert len(calls) == 2


# --- chat-command create_event (3b) ---


def test_create_event_builds_allowlisted_gws_argv():
    """build_args → argv CODE-fixed trong _GWS_ALLOWLIST_PREFIXES; slots chỉ vào --json;
    action qua Lớp A sạch (không phải NHỜ allowlist rộng — mà vì đúng prefix cho phép)."""
    import json as _json

    from my_crew.actions.hard_block import _hard_deny_gws

    pack = PackRegistry().load("personal")
    spec = pack.commands["create_event"]
    payload = spec["build_args"](
        {"title": "Họp thử", "start": "2026-08-05T09:00:00+07:00"}, None
    )
    assert payload["argv"][:3] == ["calendar", "events", "insert"]
    params = _json.loads(payload["argv"][payload["argv"].index("--params") + 1])
    assert params == {"calendarId": "primary"}  # path-param bắt buộc — thiếu là API 400
    body = _json.loads(payload["argv"][payload["argv"].index("--json") + 1])
    assert body["summary"] == "Họp thử"
    assert body["start"] == {"dateTime": "2026-08-05T09:00:00+07:00"}
    assert payload["dedup_hint"].startswith("personal-calendar:Họp thử:")
    action = {**payload, "type": "gws_write"}
    assert _hard_deny_gws(action) is None  # qua Lớp A vì đúng prefix — không phải may


def test_create_event_destructive_slot_cannot_escape_argv():
    """Slot chứa verb phá hoại chỉ nằm TRONG --json body (tiêu đề sự kiện), không bao giờ
    thành subcommand — và một argv chế tay có 'delete' vẫn bị Lớp A marker chặn."""
    from my_crew.actions.hard_block import _hard_deny_gws

    pack = PackRegistry().load("personal")
    payload = pack.commands["create_event"]["build_args"](
        {"title": "delete share acl", "start": "2026-08-05T09:00:00+07:00"}, None
    )
    assert payload["argv"][:3] == ["calendar", "events", "insert"]  # verb không đổi argv
    forged = {"type": "gws_write", "argv": ["calendar", "events", "delete", "--json", "{}"],
              "dedup_hint": "x"}
    verdict = _hard_deny_gws(forged)
    assert verdict is not None and verdict.blocked  # Lớp A giữ nguyên


# --- chat-command send_email (v58) ---


def test_vetted_command_types_exact_set():
    """Pin: bề mặt catalog không được phình mà không ai để ý. Mọi lần mở rộng phải là
    quyết định có chủ đích + sửa pin này kèm lý do. v58: rút email_send (mail đi gws).
    v65: thêm reminder_create/reminder_cancel (nhắc hẹn giờ, actor-bound store write,
    có nhánh Lớp A riêng — CEO duyệt 2026-08-04)."""
    from my_crew.packs.registry import _VETTED_COMMAND_TYPES

    assert _VETTED_COMMAND_TYPES == frozenset(
        {"mcp_tool", "schedule_update", "team_task_create", "team_task_move", "gws_write",
         "reminder_create", "reminder_cancel"}
    )


def test_send_email_builds_gws_send_argv(monkeypatch):
    from my_crew.actions.hard_block import _hard_deny_gws

    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/gws")  # CI không cài gws
    pack = PackRegistry().load("personal")
    spec = pack.commands["send_email"]
    assert spec["type"] == "gws_write"  # OAuth gws, không SMTP
    payload = spec["build_args"](
        {"to": "a@b.com", "subject": "Chào", "body": "Nội dung."}, None
    )
    assert payload["argv"][:2] == ["gmail", "+send"]
    assert payload["argv"][2:] == ["--to", "a@b.com", "--subject", "Chào",
                                   "--body", "Nội dung."]
    assert payload["dedup_hint"].startswith("personal-email:a@b.com:Chào:")
    assert _hard_deny_gws({**payload, "type": "gws_write"}) is None  # qua Lớp A đúng prefix
    # Field lạ (kể cả attachment_path bịa) chết từ vòng schema — không tới build_args.
    from my_crew.agent.chat_command import validate_args

    _, err = validate_args(spec, {"to": "a@b.com", "subject": "s", "body": "b",
                                  "attachment_path": "/tmp/x.xlsx"})
    assert err is not None and "attachment_path" in err


def test_send_email_accepts_multiple_recipients(monkeypatch):
    """UAT vòng 2 pattern D: 'gửi cho A và B' bị regex 1-địa-chỉ chặn oan — gws +send
    nhận comma-separated. Schema nới cho danh sách, build_args chuẩn hoá khoảng trắng."""
    from my_crew.agent.chat_command import validate_args

    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/gws")  # CI không cài gws
    pack = PackRegistry().load("personal")
    spec = pack.commands["send_email"]
    clean, err = validate_args(
        spec, {"to": "a@b.com , c@d.org,e@f.vn", "subject": "s", "body": "b"}
    )
    assert err is None
    payload = spec["build_args"](clean, None)
    assert payload["argv"][2:4] == ["--to", "a@b.com,c@d.org,e@f.vn"]
    # nửa vời vẫn chết: phần tử không phải email, hoặc phẩy treo cuối
    for bad in ("a@b.com, không-phải-email", "a@b.com,", ",a@b.com", "a@b.com;c@d.org"):
        _, err = validate_args(spec, {"to": bad, "subject": "s", "body": "b"})
        assert err is not None, bad


def test_send_email_without_gws_cli_fails_with_user_message(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    pack = PackRegistry().load("personal")
    with pytest.raises(ValueError, match="gws"):
        pack.commands["send_email"]["build_args"](
            {"to": "a@b.com", "subject": "s", "body": "b"}, None
        )


def test_email_layer_a_still_scans_secrets():
    """Nới catalog KHÔNG nới Lớp A: body chứa credential vẫn bị hard-deny.

    Token giả ghép lúc chạy để file test không chứa literal dạng secret."""
    from my_crew.actions.hard_block import classify

    fake_token = "ghp_" + "a1b2c3d4" * 5  # noqa: S105 — giả, ghép runtime
    action = {"type": "gws_write",
              "argv": ["gmail", "+send", "--to", "a@b.com", "--subject", "s",
                       "--body", f"token: {fake_token}"], "dedup_hint": "x"}
    verdict = classify(action)
    assert verdict.blocked  # secret trong body vẫn chết ở _credential_verdict


# --- v60: sửa/xoá lịch ---


def _stub_events(monkeypatch, events):
    monkeypatch.setattr(
        "my_crew.tools.gws_read.calendar_events_window", lambda q="", days=14: events
    )


_EV = {"id": "abc123DEF", "summary": "Họp với anh Minh",
       "start": {"dateTime": "2026-08-05T09:00:00+07:00"},
       "end": {"dateTime": "2026-08-05T09:30:00+07:00"}}


def test_update_event_patch_keeps_old_duration(monkeypatch):
    import json

    _stub_events(monkeypatch, [_EV])
    pack = PackRegistry().load("personal")
    payload = pack.commands["update_event"]["build_args"](
        {"title": "anh Minh", "new_start": "2026-08-05T14:00:00+07:00"}, None
    )
    assert payload["argv"][:3] == ["calendar", "events", "patch"]
    params = json.loads(payload["argv"][4])
    assert params == {"calendarId": "primary", "eventId": "abc123DEF"}
    body = json.loads(payload["argv"][6])
    assert body["start"]["dateTime"] == "2026-08-05T14:00:00+07:00"
    assert body["end"]["dateTime"].startswith("2026-08-05T14:30")  # duration 30' giữ nguyên
    # qua Lớp A: patch nằm trong prefix table, không dính marker
    from my_crew.actions.hard_block import _hard_deny_gws

    assert _hard_deny_gws({**payload, "type": "gws_write"}) is None


def test_update_event_resolver_zero_and_many_matches_ask_back(monkeypatch):
    pack = PackRegistry().load("personal")
    build = pack.commands["update_event"]["build_args"]
    _stub_events(monkeypatch, [])
    with pytest.raises(ValueError, match="không thấy lịch"):
        build({"title": "hop ma", "new_start": "2026-08-05T14:00:00+07:00"}, None)
    _stub_events(monkeypatch, [_EV, {**_EV, "id": "zzz999", "summary": "Họp với anh Minh 2"}])
    with pytest.raises(ValueError, match="nói cụ thể"):
        build({"title": "anh Minh", "new_start": "2026-08-05T14:00:00+07:00"}, None)


def test_at_hint_disambiguates_same_title(monkeypatch):
    """Trùng tên → arg `at` (prefix ngày/giờ) chọn đúng một event."""
    import json

    twin = {**_EV, "id": "zzz999",
            "start": {"dateTime": "2026-08-06T09:00:00+07:00"},
            "end": {"dateTime": "2026-08-06T09:30:00+07:00"}}
    _stub_events(monkeypatch, [_EV, twin])
    pack = PackRegistry().load("personal")
    payload = pack.commands["delete_event"]["build_args"](
        {"title": "anh Minh", "at": "2026-08-06"}, None
    )
    assert json.loads(payload["argv"][4])["eventId"] == "zzz999"


def test_delete_event_delete_argv_passes_carveout(monkeypatch):
    from my_crew.actions.hard_block import _hard_deny_gws

    _stub_events(monkeypatch, [_EV])
    pack = PackRegistry().load("personal")
    payload = pack.commands["delete_event"]["build_args"]({"title": "anh Minh"}, None)
    assert payload["argv"][:3] == ["calendar", "events", "delete"]
    assert payload["dedup_hint"] == "personal-calendar-del:abc123DEF"
    assert _hard_deny_gws({**payload, "type": "gws_write"}) is None


def test_calendar_delete_carveout_rejects_every_variant():
    """Pin an ninh v60: carve-out CHỈ mở đúng một shape. Mọi biến thể lệch — service
    khác, calendar khác, thêm flag, params sai key, eventId shape lạ — chết như cũ."""
    import json

    from my_crew.actions.hard_block import _hard_deny_gws

    good_params = json.dumps({"calendarId": "primary", "eventId": "abc123DEF"})
    variants = [
        ["sheets", "delete", "--params", good_params],
        ["drive", "files", "delete", "--params", good_params],
        ["calendar", "calendars", "delete", "--params", good_params],
        ["calendar", "events", "delete", "--params",
         json.dumps({"calendarId": "team@group.calendar.google.com", "eventId": "abc123"})],
        ["calendar", "events", "delete", "--params",
         json.dumps({"calendarId": "primary", "eventId": "abc123", "sendUpdates": "all"})],
        ["calendar", "events", "delete", "--params", good_params, "--json", "{}"],
        ["calendar", "events", "delete", "--params", "not-json"],
        ["calendar", "events", "delete"],
        ["calendar", "events", "delete", "--params",
         json.dumps({"calendarId": "primary", "eventId": "x y z"})],
    ]
    for argv in variants:
        verdict = _hard_deny_gws({"type": "gws_write", "argv": argv, "dedup_hint": "x"})
        assert verdict is not None and verdict.blocked, argv
    # và share/permission markers vẫn vô điều kiện, kể cả kèm shape delete hợp lệ
    verdict = _hard_deny_gws({"type": "gws_write", "dedup_hint": "x",
                              "argv": ["calendar", "acl", "insert", "--params", "{}"]})
    assert verdict is not None and verdict.blocked


def test_briefing_gateway_denies_mcp_with_empty_pack_allowlist(tmp_path):
    """H1 regression: allowlist rỗng KHÔNG được `or None` thành allowlist mặc định rộng.

    Dùng đúng cách graph dựng gateway (mcp_allowlist=pack.allowlist) — một mcp_tool
    nằm trong allowlist mặc định của core (slack post_message) phải bị DENY."""
    from my_crew.actions.hard_block import classify

    pack = PackRegistry().load("personal")
    verdict = classify(
        {"type": "mcp_tool", "server": "slack", "tool": "post_message", "args": {}},
        allowlist=pack.allowlist,
    )
    assert verdict.blocked  # default-DENY thật sự — không rơi về allowlist core


def test_no_gateway_construction_resurrects_default_allowlist():
    """H1 sót (UAT vòng 2): telegram_inbox/inbox/task_runner còn `pack.allowlist or None`
    — với pack allowlist rỗng (personal/office) điều đó hồi sinh allowlist MCP mặc định
    rộng của core ngay trên đường xử lý chat thật. Pin toàn bộ source: cấm pattern này."""
    import re
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    code_line = re.compile(r"^\s*mcp_allowlist\s*=.*\bor None\b")  # code thật, bỏ docstring
    offenders = [
        str(path.relative_to(repo))
        for scan_root in (repo / "my_crew", repo / "domain-packs")
        for path in scan_root.rglob("*.py")
        if any(code_line.match(line) for line in
               path.read_text(encoding="utf-8").splitlines())
    ]
    assert offenders == []
