"""P6: ads-pack — Meta Ads insight report, Telegram DM push. Offline.

Load-bearing properties:

- Pack assembly: discovery thấy `ads`; 1 kind ads-weekly; allowlist RỖNG (zero writes
  MVP — tạo/sửa campaign ngoài scope); prompt ads-weekly-system có mặt.
- fetch_campaign_insights: mock `urllib.request.urlopen` (KHÔNG có token/app Meta thật —
  test toàn bộ bằng mock HTTP, theo đúng ràng buộc phase). 4xx/5xx/network/malformed-JSON
  đều raise MetaInsightsError — không bao giờ trả về hàng giả.
- AdsToolProvider.read: thiếu ADS_META_AD_ACCOUNT_ID ⇒ raise (lỗi cấu hình, fail-loud);
  MetaInsightsError từ API ⇒ trả None (fail-degrade, không crash).
- build_ads_weekly / render_ads_weekly_text: rows=None ⇒ available=False ⇒ render "THIẾU"
  cho từng số liệu — không bao giờ bịa số.
- Graph ads-weekly chạy offline end-to-end: dry-run delivery tính là giao; thiếu telegram
  ⇒ skip có tiếng; audience external ⇒ fail loud.
"""

from __future__ import annotations

import dataclasses
import json
import urllib.error

import pytest

from my_crew.config.config_builders import (
    build_reporting_config_from_dict,
    build_settings_from_dict,
)
from my_crew.config.telegram_config import TelegramConfig
from my_crew.packs.registry import PackRegistry, discover_domains

# --- pack assembly ---


def test_ads_pack_discovered_and_assembled():
    assert "ads" in discover_domains()
    pack = PackRegistry().load("ads")
    assert set(pack.report_kinds) == {"ads-weekly"}
    assert pack.allowlist == {}  # zero writes in the MVP
    assert "ads-weekly-system" in pack.prompts
    assert pack.tools is not None
    assert pack.commands == {}


# --- fetch_campaign_insights: mocked HTTP only (no real Meta token exists) ---


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _json_bytes(obj) -> bytes:
    return json.dumps(obj).encode("utf-8")


def test_fetch_campaign_insights_happy_path(monkeypatch):
    from domain_pack_ads.tools import fetch_campaign_insights

    payload = {
        "data": [
            {"campaign_id": "1", "campaign_name": "Sale Tết", "date_start": "2026-08-24",
             "spend": "120.5", "reach": "3000", "ctr": "0.021"},
            {"campaign_id": "1", "campaign_name": "Sale Tết", "date_start": "2026-08-25",
             "spend": "80", "reach": "1500", "ctr": "0.018"},
        ]
    }
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda req, timeout=None: _FakeResponse(_json_bytes(payload))
    )
    rows = fetch_campaign_insights("123456", token="tok")
    assert len(rows) == 2
    assert rows[0].campaign_name == "Sale Tết"
    assert rows[0].spend == 120.5
    assert rows[0].reach == 3000


def test_fetch_campaign_insights_http_error_raises(monkeypatch):
    from domain_pack_ads.tools import MetaInsightsError, fetch_campaign_insights

    def _boom(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url if hasattr(req, "full_url") else "url", 401, "Unauthorized",
            hdrs=None, fp=None,
        )

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    with pytest.raises(MetaInsightsError, match="HTTP 401"):
        fetch_campaign_insights("123456", token="bad-token")


def test_fetch_campaign_insights_network_error_raises(monkeypatch):
    from domain_pack_ads.tools import MetaInsightsError, fetch_campaign_insights

    def _boom(req, timeout=None):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    with pytest.raises(MetaInsightsError, match="network error"):
        fetch_campaign_insights("123456", token="tok")


def test_fetch_campaign_insights_malformed_json_raises(monkeypatch):
    from domain_pack_ads.tools import MetaInsightsError, fetch_campaign_insights

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda req, timeout=None: _FakeResponse(b"not json")
    )
    with pytest.raises(MetaInsightsError, match="non-JSON"):
        fetch_campaign_insights("123456", token="tok")


def test_fetch_campaign_insights_missing_data_key_raises(monkeypatch):
    from domain_pack_ads.tools import MetaInsightsError, fetch_campaign_insights

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: _FakeResponse(_json_bytes({"error": {"message": "bad"}})),
    )
    with pytest.raises(MetaInsightsError, match="missing 'data'"):
        fetch_campaign_insights("123456", token="tok")


# --- AdsToolProvider.read: config-missing raises, API-failure degrades to None ---


def test_tool_provider_raises_when_ad_account_id_missing(monkeypatch):
    from domain_pack_ads.tools import AdsToolProvider

    monkeypatch.delenv("ADS_META_AD_ACCOUNT_ID", raising=False)
    with pytest.raises(RuntimeError, match="ADS_META_AD_ACCOUNT_ID"):
        AdsToolProvider().read("ads-weekly", None, None)


def test_tool_provider_degrades_to_none_on_api_failure(monkeypatch):
    import domain_pack_ads.tools as ads_tools
    from domain_pack_ads.tools import AdsToolProvider, MetaInsightsError

    def _boom(*a, **k):
        raise MetaInsightsError("boom")

    monkeypatch.setenv("ADS_META_AD_ACCOUNT_ID", "123456")
    monkeypatch.setenv("ADS_META_TOKEN", "tok")
    monkeypatch.setattr(ads_tools, "_resolve_token", lambda settings: "tok")
    monkeypatch.setattr(ads_tools, "fetch_campaign_insights", _boom)
    assert AdsToolProvider().read("ads-weekly", None, None) is None


def test_tool_provider_happy_path_returns_rows(monkeypatch):
    import domain_pack_ads.tools as ads_tools
    from domain_pack_ads.tools import AdsToolProvider, InsightRow

    monkeypatch.setenv("ADS_META_AD_ACCOUNT_ID", "123456")
    monkeypatch.setattr(ads_tools, "_resolve_token", lambda settings: "tok")
    fake_rows = [InsightRow("1", "Sale", "2026-08-24", 100.0, 2000, 0.02)]
    monkeypatch.setattr(ads_tools, "fetch_campaign_insights", lambda *a, **k: fake_rows)
    assert AdsToolProvider().read("ads-weekly", None, None) == fake_rows


# --- credential-resolution failures degrade to None, never crash (regression) ---
#
# `resolve_service_credentials` (P4) can raise 3 exception shapes on top of
# MetaInsightsError: CredentialStoreError (unset token_env / bad master key),
# CredentialDecryptError (its subclass — no/corrupt stored credential), and
# ValueError (malformed account-id shape). Each used to escape `AdsToolProvider
# .read`'s narrower `except MetaInsightsError` and crash the whole graph run —
# most commonly hit the moment a fresh ads agent is created and the operator
# has not filled in ADS_META_TOKEN yet (exactly the state the template tells
# them to leave for later). These tests exercise the real failure path through
# `resolve_service_credentials` (not a mocked `_resolve_token`) and go through
# `graphs.py`'s `perceive` node — the actual path a user's scheduled run takes —
# not just `AdsToolProvider.read` in isolation.


def test_tool_provider_degrades_on_missing_token_env(monkeypatch):
    """The single most common case: a freshly created ads agent, operator has not
    filled in ADS_META_TOKEN yet. Must degrade, never raise."""
    from domain_pack_ads.tools import AdsToolProvider

    monkeypatch.setenv("ADS_META_AD_ACCOUNT_ID", "123456")
    monkeypatch.delenv("ADS_META_TOKEN", raising=False)
    assert AdsToolProvider().read("ads-weekly", None, None) is None


def test_tool_provider_degrades_on_credential_decrypt_error(monkeypatch):
    """settings.ads_credential referencing an account with no stored credential ⇒
    CredentialStore.get raises CredentialDecryptError (a CredentialStoreError
    subclass) — must degrade, not raise."""
    from domain_pack_ads.tools import AdsToolProvider

    monkeypatch.setenv("ADS_META_AD_ACCOUNT_ID", "123456")

    class _Settings:
        ads_credential = {"account": "no-such-account"}

    assert AdsToolProvider().read("ads-weekly", None, _Settings()) is None


def test_tool_provider_degrades_on_bad_account_id_value_error(monkeypatch):
    """settings.ads_credential with a malformed account id ⇒ CredentialStore.get's
    internal _validate_account_id raises a bare ValueError — must degrade."""
    from domain_pack_ads.tools import AdsToolProvider

    monkeypatch.setenv("ADS_META_AD_ACCOUNT_ID", "123456")

    class _Settings:
        ads_credential = {"account": "BAD/ID"}

    assert AdsToolProvider().read("ads-weekly", None, _Settings()) is None


def test_tool_provider_degrades_on_credential_store_error(monkeypatch):
    """token_env configured but pointing at an unset/empty env var ⇒
    resolve_service_credentials raises CredentialStoreError directly — must degrade."""
    from domain_pack_ads.tools import AdsToolProvider

    monkeypatch.setenv("ADS_META_AD_ACCOUNT_ID", "123456")
    monkeypatch.delenv("SOME_UNSET_ADS_TOKEN_VAR", raising=False)

    class _Settings:
        ads_credential = {"token_env": "SOME_UNSET_ADS_TOKEN_VAR"}

    assert AdsToolProvider().read("ads-weekly", None, _Settings()) is None


def test_ads_weekly_graph_missing_token_degrades_through_perceive_node(monkeypatch, tmp_path):
    """End-to-end regression for C1: run the REAL graph (not a fake ToolProvider) with
    no ADS_META_TOKEN set. `perceive` calls `tools.read(...)` un-guarded — this must
    reach `compose_report` and render THIẾU, not raise out of `graph.invoke`."""
    monkeypatch.delenv("ADS_META_TOKEN", raising=False)
    monkeypatch.setenv("ADS_META_AD_ACCOUNT_ID", "123456")

    pack = PackRegistry().load("ads")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": True})
    graph = pack.report_kinds["ads-weekly"](
        None, config=_config(True), settings=settings,  # tools=None ⇒ real AdsToolProvider
    )
    result = graph.invoke({})
    assert "THIẾU" in result["report_text"]


def test_ads_weekly_graph_credential_decrypt_error_degrades_through_perceive_node(
    monkeypatch, tmp_path
):
    """End-to-end regression for C1: settings.ads_credential points at a non-existent
    stored account ⇒ CredentialDecryptError inside `perceive`. Must degrade to THIẾU,
    not propagate out of `graph.invoke`."""
    monkeypatch.setenv("ADS_META_AD_ACCOUNT_ID", "123456")

    pack = PackRegistry().load("ads")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": True})
    object.__setattr__(settings, "ads_credential", {"account": "no-such-account"})
    graph = pack.report_kinds["ads-weekly"](
        None, config=_config(True), settings=settings,
    )
    result = graph.invoke({})
    assert "THIẾU" in result["report_text"]


# --- analyzers: pure functions, THIẾU sentinel on degrade ---


def test_build_ads_weekly_aggregates_by_campaign():
    from domain_pack_ads.analyzers import build_ads_weekly
    from domain_pack_ads.tools import InsightRow

    rows = [
        InsightRow("1", "Sale Tết", "2026-08-24", 100.0, 2000, 0.02),
        InsightRow("1", "Sale Tết", "2026-08-25", 50.0, 1000, 0.03),
        InsightRow("2", "Brand Awareness", "2026-08-24", 200.0, 5000, 0.01),
    ]
    report = build_ads_weekly(rows)
    assert report.available is True
    assert report.total_spend == 350.0
    assert report.total_reach == 8000
    assert len(report.campaigns) == 2
    assert report.campaigns[0].campaign_name == "Brand Awareness"  # sorted by -spend


def test_build_ads_weekly_none_is_degraded():
    from domain_pack_ads.analyzers import build_ads_weekly

    report = build_ads_weekly(None)
    assert report.available is False
    assert report.total_spend == 0.0
    assert report.campaigns == ()


def test_build_ads_weekly_empty_list_is_not_degraded():
    from domain_pack_ads.analyzers import build_ads_weekly

    report = build_ads_weekly([])
    assert report.available is True  # source answered fine, just no campaigns ran
    assert report.total_spend == 0.0


def test_render_ads_weekly_text_degraded_shows_thieu():
    from domain_pack_ads.analyzers import THIEU, build_ads_weekly, render_ads_weekly_text

    report = build_ads_weekly(None)
    text = render_ads_weekly_text(report, "2026-08-30")
    assert THIEU in text
    assert text.count(THIEU) == 2  # spend + reach, never fabricated


def test_render_ads_weekly_text_happy_path_no_thieu():
    from domain_pack_ads.analyzers import THIEU, build_ads_weekly, render_ads_weekly_text
    from domain_pack_ads.tools import InsightRow

    report = build_ads_weekly([InsightRow("1", "Sale", "2026-08-24", 100.0, 2000, 0.02)])
    text = render_ads_weekly_text(report, "2026-08-30")
    assert THIEU not in text
    assert "Sale" in text


# --- offline end-to-end graph run ---


class _FakeAdsTools:
    def __init__(self, rows):
        self._rows = rows

    def read(self, kind, config, settings):
        return self._rows


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


def test_ads_weekly_graph_offline_dry_run_delivers_to_telegram(tmp_path):
    from domain_pack_ads.tools import InsightRow

    pack = PackRegistry().load("ads")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": True})  # no API key
    graph = pack.report_kinds["ads-weekly"](
        None, config=_config(True), settings=settings,
        tools=_FakeAdsTools([InsightRow("1", "Sale", "2026-08-24", 100.0, 2000, 0.02)]),
    )
    result = graph.invoke({})
    assert result["delivered"] is True
    assert result["delivery_summary"] == "telegram=dry_run"
    assert "Sale" in result["report_text"]


def test_ads_weekly_graph_degraded_source_renders_thieu(tmp_path):
    pack = PackRegistry().load("ads")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": True})
    graph = pack.report_kinds["ads-weekly"](
        None, config=_config(True), settings=settings, tools=_FakeAdsTools(None),
    )
    result = graph.invoke({})
    assert "THIẾU" in result["report_text"]


def test_ads_weekly_graph_without_telegram_skips_loudly(tmp_path):
    pack = PackRegistry().load("ads")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": True})
    graph = pack.report_kinds["ads-weekly"](
        None, config=_config(False), settings=settings, tools=_FakeAdsTools([]),
    )
    result = graph.invoke({})
    assert result["delivered"] is False
    assert result["delivery_summary"] == "telegram=not_configured"


def test_ads_weekly_graph_rejects_external_audience(tmp_path):
    pack = PackRegistry().load("ads")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": True})
    with pytest.raises(ValueError, match="internal"):
        pack.report_kinds["ads-weekly"](
            None, config=_config(True), settings=settings, audience="external",
            tools=_FakeAdsTools([]),
        )
