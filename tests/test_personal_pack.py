"""v57: personal-pack — thư ký riêng, kênh Telegram DM. Offline.

Load-bearing properties:

- Pack assembly: discovery thấy `personal`; đúng 1 kind `briefing`; allowlist RỖNG
  (thư ký không ghi MCP nào — default-DENY nguyên vẹn); prompts qa-system +
  briefing-system có mặt (qa-system là persona chat DM, seam qa_answer.py).
- ToolProvider thuần code, chạy offline, trả bối cảnh ngày tiếng Việt.
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
    assert set(pack.report_kinds) == {"briefing"}
    assert pack.allowlist == {}  # thư ký không ghi MCP nào — default-DENY nguyên vẹn
    assert "qa-system" in pack.prompts
    assert "briefing-system" in pack.prompts
    assert pack.tools is not None
    assert pack.commands == {}  # chưa có catalog lệnh chat — chỉ Q&A


def test_tool_provider_reads_offline_day_context():
    pack = PackRegistry().load("personal")
    snapshot = pack.tools.read("briefing", None, None)
    assert snapshot["bay_gio"]  # ISO local time
    assert snapshot["thu"].startswith(("Thứ", "Chủ"))
    assert snapshot["nguon_da_noi"] == []


# --- offline end-to-end graph run ---


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
    graph = pack.report_kinds["briefing"](None, config=_config(True), settings=settings)
    result = graph.invoke({})
    assert result["delivered"] is True  # dry-run delivery tính là giao
    assert result["delivery_summary"] == "telegram=dry_run"
    # Không API key ⇒ compose rơi về fallback thuần code — vẫn có ngày giờ, không bịa.
    assert "Hôm nay là" in result["report_text"]


def test_briefing_graph_without_telegram_skips_loudly(tmp_path):
    pack = PackRegistry().load("personal")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": True})
    graph = pack.report_kinds["briefing"](None, config=_config(False), settings=settings)
    result = graph.invoke({})
    assert result["delivered"] is False
    assert result["delivery_summary"] == "telegram=not_configured"


def test_briefing_graph_rejects_external_audience(tmp_path):
    pack = PackRegistry().load("personal")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": True})
    with pytest.raises(ValueError, match="internal"):
        pack.report_kinds["briefing"](
            None, config=_config(True), settings=settings, audience="external"
        )


def test_briefing_live_send_dedups_per_day(tmp_path, monkeypatch):
    """Non-dry-run qua gateway THẬT (api_call stub): lần 1 gửi, lần 2 CÙNG NGÀY bị dedup.

    Chốt chặn cho dedup_hint `personal-briefing:{chat}:{date}` — dry-run return trước
    tầng dedup nên test dry-run không bao giờ chạm được hành vi này."""
    calls: list[dict] = []
    monkeypatch.setenv("TK_TEST_BOT_TOKEN", "test-token")
    monkeypatch.setattr(
        "my_crew.actions.telegram_write.api_call",
        lambda token, method, payload: calls.append(payload) or {"message_id": 7},
    )
    pack = PackRegistry().load("personal")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": False})
    config = _config(True)
    first = pack.report_kinds["briefing"](None, config=config, settings=settings).invoke({})
    second = pack.report_kinds["briefing"](None, config=config, settings=settings).invoke({})
    assert first["delivered"] is True
    assert first["delivery_summary"] == "telegram=executed"
    assert len(calls) == 1  # đúng 1 lần chạm Bot API
    assert second["delivered"] is False  # cùng ngày ⇒ dedup, không gửi lại
    assert second["delivery_summary"] == "telegram=deduplicated"
    assert len(calls) == 1


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
