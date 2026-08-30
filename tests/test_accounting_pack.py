"""P6: accounting-pack — ledger cashflow report (Sheet/CSV), Telegram DM push. Offline.

Load-bearing properties:

- Pack assembly: discovery thấy `accounting`; 1 kind cashflow-weekly; write_handlers
  ALLOWLIST rỗng (write thật đi qua commands.py::gws_write, không phải ALLOWLIST);
  command `append_ledger_row` có mặt, kiểu gws_write.
- rows_to_ledger: header+data → LedgerRow; thiếu date/amount ⇒ skip (không ép về 0);
  amount không parse được ⇒ skip; phân loại thu/chi/unknown theo token tiếng Việt/Anh.
- AccountingToolProvider.read: thiếu cả ACCOUNTING_SHEET_ID lẫn ACCOUNTING_LEDGER_CSV_PATH
  ⇒ raise (lỗi cấu hình, fail-loud); LedgerReadError (gws/CSV lỗi) ⇒ trả None (fail-degrade);
  có Sheet id ⇒ ưu tiên Sheet hơn CSV.
- build_cashflow_weekly / render_cashflow_weekly_text: rows=None ⇒ available=False ⇒ THIẾU
  cho từng số liệu — không bao giờ bịa số. rows=[] hợp lệ (không phải degraded).
- Graph cashflow-weekly chạy offline end-to-end: dry-run delivery tính là giao; thiếu
  telegram ⇒ skip có tiếng; audience external ⇒ fail loud.
- append_ledger_row: pin đúng sheet đã cấu hình (không cho chọn sheet khác); guarded theo
  mặc định (Lớp B) — không bao giờ tự động thực thi trong chế độ guarded.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess

import pytest

from my_crew.actions.action_gateway import ActionGateway
from my_crew.config.config_builders import (
    build_reporting_config_from_dict,
    build_settings_from_dict,
)
from my_crew.config.telegram_config import TelegramConfig
from my_crew.packs.registry import PackRegistry, discover_domains

# --- pack assembly ---


def test_accounting_pack_discovered_and_assembled():
    assert "accounting" in discover_domains()
    pack = PackRegistry().load("accounting")
    assert set(pack.report_kinds) == {"cashflow-weekly"}
    assert pack.allowlist == {}  # real write goes through commands.py::gws_write
    assert "cashflow-weekly-system" in pack.prompts
    assert pack.tools is not None
    assert set(pack.commands) == {"append_ledger_row"}
    assert pack.commands["append_ledger_row"]["type"] == "gws_write"


# --- rows_to_ledger: pure mapping, skip-not-guess posture ---


def test_rows_to_ledger_happy_path_classifies_thu_chi():
    from domain_pack_accounting.tools import rows_to_ledger

    rows = [
        ["date", "type", "amount", "description"],
        ["2026-08-24", "thu", "1,000,000", "Bán hàng"],
        ["2026-08-25", "chi", "200000", "Mua văn phòng phẩm"],
        ["2026-08-26", "khác", "50000", "Không rõ loại"],
    ]
    ledger = rows_to_ledger(rows)
    assert len(ledger) == 3
    assert ledger[0].kind == "income" and ledger[0].amount == 1_000_000.0
    assert ledger[1].kind == "expense" and ledger[1].amount == 200_000.0
    assert ledger[2].kind == "unknown"


def test_rows_to_ledger_skips_blank_and_missing_date_or_amount():
    from domain_pack_accounting.tools import rows_to_ledger

    rows = [
        ["date", "type", "amount", "description"],
        ["", "", "", ""],  # fully blank
        ["", "thu", "100", "no date"],  # missing date
        ["2026-08-24", "chi", "", "no amount"],  # missing amount
        ["2026-08-24", "thu", "100", "ok"],
    ]
    ledger = rows_to_ledger(rows)
    assert len(ledger) == 1
    assert ledger[0].description == "ok"


def test_rows_to_ledger_skips_unparseable_amount_never_guesses():
    from domain_pack_accounting.tools import rows_to_ledger

    rows = [
        ["date", "type", "amount", "description"],
        ["2026-08-24", "thu", "not-a-number", "bad amount"],
    ]
    assert rows_to_ledger(rows) == []


def test_rows_to_ledger_empty_input_returns_empty():
    from domain_pack_accounting.tools import rows_to_ledger

    assert rows_to_ledger([]) == []


# --- read-layer transports: gws subprocess + CSV file ---


def test_gws_sheet_rows_parses_values(monkeypatch):
    from domain_pack_accounting.tools import _gws_sheet_rows

    def _fake_run(argv, **kw):
        assert argv[:4] == ["gws", "sheets", "spreadsheets", "values"]
        return subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps({"values": [["date", "type"], ["2026-08-24", "thu"]]}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    rows = _gws_sheet_rows("SHEET1", "A1:F1000")
    assert rows == [["date", "type"], ["2026-08-24", "thu"]]


def test_gws_sheet_rows_missing_binary_raises_ledger_read_error(monkeypatch):
    from domain_pack_accounting.tools import LedgerReadError, _gws_sheet_rows

    def _fake_run(argv, **kw):
        raise FileNotFoundError("gws not found")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(LedgerReadError, match="gws CLI not found"):
        _gws_sheet_rows("SHEET1", "A1:F1000")


def test_gws_sheet_rows_nonzero_exit_raises(monkeypatch):
    from domain_pack_accounting.tools import LedgerReadError, _gws_sheet_rows

    def _fake_run(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="permission denied")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(LedgerReadError, match="permission denied"):
        _gws_sheet_rows("SHEET1", "A1:F1000")


def test_gws_sheet_rows_no_values_key_raises(monkeypatch):
    from domain_pack_accounting.tools import LedgerReadError, _gws_sheet_rows

    def _fake_run(argv, **kw):
        return subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps({"error": {"message": "bad range"}}), stderr=""
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(LedgerReadError, match="no values"):
        _gws_sheet_rows("SHEET1", "A1:F1000")


def test_csv_rows_reads_real_file(tmp_path):
    from domain_pack_accounting.tools import _csv_rows

    csv_path = tmp_path / "ledger.csv"
    csv_path.write_text("date,type,amount,description\n2026-08-24,thu,100,ok\n", encoding="utf-8")
    rows = _csv_rows(csv_path)
    assert rows == [["date", "type", "amount", "description"], ["2026-08-24", "thu", "100", "ok"]]


def test_csv_rows_missing_file_raises_ledger_read_error(tmp_path):
    from domain_pack_accounting.tools import LedgerReadError, _csv_rows

    with pytest.raises(LedgerReadError, match="cannot read ledger CSV"):
        _csv_rows(tmp_path / "does-not-exist.csv")


# --- AccountingToolProvider.read: config-missing raises, source-broken degrades ---


def test_tool_provider_raises_when_no_source_configured(monkeypatch):
    from domain_pack_accounting.tools import AccountingToolProvider

    monkeypatch.delenv("ACCOUNTING_SHEET_ID", raising=False)
    monkeypatch.delenv("ACCOUNTING_LEDGER_CSV_PATH", raising=False)
    with pytest.raises(RuntimeError, match="needs a data source"):
        AccountingToolProvider().read("cashflow-weekly", None, None)


def test_tool_provider_degrades_to_none_on_sheet_read_error(monkeypatch):
    import domain_pack_accounting.tools as acct_tools
    from domain_pack_accounting.tools import AccountingToolProvider, LedgerReadError

    def _boom(*a, **k):
        raise LedgerReadError("boom")

    monkeypatch.setenv("ACCOUNTING_SHEET_ID", "SHEET1")
    monkeypatch.delenv("ACCOUNTING_LEDGER_CSV_PATH", raising=False)
    monkeypatch.setattr(acct_tools, "_gws_sheet_rows", _boom)
    assert AccountingToolProvider().read("cashflow-weekly", None, None) is None


def test_gws_sheet_rows_truncated_json_raises_ledger_read_error(monkeypatch):
    """Regression for C2: `gws` stdout has a `{` (passes the brace-found check) but the
    JSON is truncated/garbled (mixed banner text, a gws version bump changing output
    shape). `json.loads` used to raise a bare JSONDecodeError here, which is not a
    LedgerReadError — it escaped `AccountingToolProvider.read`'s `except LedgerReadError`
    and crashed the whole run instead of degrading to THIẾU."""
    from domain_pack_accounting.tools import LedgerReadError, _gws_sheet_rows

    def _fake_run(argv, **kw):
        return subprocess.CompletedProcess(
            argv, 0, stdout='{"values": [truncated garbage', stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(LedgerReadError, match="malformed JSON"):
        _gws_sheet_rows("SHEET1", "A1:F1000")


def test_gws_sheet_rows_non_json_after_brace_raises_ledger_read_error(monkeypatch):
    """A `{` can appear in stdout without any valid JSON following it at all (e.g. a
    log line containing a literal brace before the real error text) — also must
    degrade via LedgerReadError, not a bare JSONDecodeError."""
    from domain_pack_accounting.tools import LedgerReadError, _gws_sheet_rows

    def _fake_run(argv, **kw):
        return subprocess.CompletedProcess(
            argv, 0, stdout="warning: {something} unrelated, not json at all", stderr="",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(LedgerReadError, match="malformed JSON"):
        _gws_sheet_rows("SHEET1", "A1:F1000")


def test_csv_rows_malformed_field_raises_ledger_read_error(tmp_path):
    """A field exceeding csv's parser limit (same failure family as an unterminated
    quoted field or an embedded null byte on some platforms) raises `csv.Error`, not
    `OSError` — the pre-fix `except OSError` in `_csv_rows` let it escape as a bare
    csv.Error, which is also not a LedgerReadError, and would crash the run the same
    way as C2's JSON case."""
    import csv

    from domain_pack_accounting.tools import LedgerReadError, _csv_rows

    csv_path = tmp_path / "ledger.csv"
    csv_path.write_text(
        "date,type,amount,description\n2026-08-24,thu,100," + ("x" * 500_000) + "\n",
        encoding="utf-8",
    )
    original_limit = csv.field_size_limit()
    csv.field_size_limit(1000)
    try:
        with pytest.raises(LedgerReadError, match="cannot parse ledger CSV"):
            _csv_rows(csv_path)
    finally:
        csv.field_size_limit(original_limit)


def test_tool_provider_degrades_to_none_on_gws_malformed_json(monkeypatch):
    """AccountingToolProvider.read must degrade (not raise) when the gws transport
    itself hits malformed JSON — same assertion as the existing
    test_tool_provider_degrades_to_none_on_sheet_read_error but exercising the real
    JSONDecodeError path end-to-end through _gws_sheet_rows rather than a mocked
    LedgerReadError."""
    from domain_pack_accounting.tools import AccountingToolProvider

    monkeypatch.setenv("ACCOUNTING_SHEET_ID", "SHEET1")
    monkeypatch.delenv("ACCOUNTING_LEDGER_CSV_PATH", raising=False)
    monkeypatch.setattr(
        subprocess, "run",
        lambda argv, **kw: subprocess.CompletedProcess(
            argv, 0, stdout='{"values": [broken', stderr="",
        ),
    )
    assert AccountingToolProvider().read("cashflow-weekly", None, None) is None


def test_cashflow_weekly_graph_gws_malformed_json_degrades_through_perceive_node(
    monkeypatch, tmp_path
):
    """End-to-end regression for C2: run the REAL graph (not a fake ToolProvider) with
    `gws` returning truncated JSON. `perceive` calls `tools.read(...)` un-guarded — this
    must reach `compose_report` and render THIẾU, not raise out of `graph.invoke`."""
    monkeypatch.setenv("ACCOUNTING_SHEET_ID", "SHEET1")
    monkeypatch.delenv("ACCOUNTING_LEDGER_CSV_PATH", raising=False)
    monkeypatch.setattr(
        subprocess, "run",
        lambda argv, **kw: subprocess.CompletedProcess(
            argv, 0, stdout='{"values": [broken', stderr="",
        ),
    )

    pack = PackRegistry().load("accounting")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": True})
    graph = pack.report_kinds["cashflow-weekly"](
        None, config=_config(True), settings=settings,  # tools=None ⇒ real AccountingToolProvider
    )
    result = graph.invoke({})
    assert "THIẾU" in result["report_text"]


def test_tool_provider_prefers_sheet_over_csv_when_both_set(monkeypatch, tmp_path):
    import domain_pack_accounting.tools as acct_tools
    from domain_pack_accounting.tools import AccountingToolProvider

    csv_path = tmp_path / "ledger.csv"
    csv_path.write_text("date,type,amount,description\n2026-08-24,chi,1,csv-should-not-be-used\n",
                         encoding="utf-8")
    monkeypatch.setenv("ACCOUNTING_SHEET_ID", "SHEET1")
    monkeypatch.setenv("ACCOUNTING_LEDGER_CSV_PATH", str(csv_path))
    monkeypatch.setattr(
        acct_tools, "_gws_sheet_rows",
        lambda *a, **k: [["date", "type", "amount", "description"],
                          ["2026-08-24", "thu", "100", "from-sheet"]],
    )
    rows = AccountingToolProvider().read("cashflow-weekly", None, None)
    assert rows is not None and rows[0].description == "from-sheet"


def test_tool_provider_falls_back_to_csv_when_no_sheet_id(monkeypatch, tmp_path):
    from domain_pack_accounting.tools import AccountingToolProvider

    csv_path = tmp_path / "ledger.csv"
    csv_path.write_text("date,type,amount,description\n2026-08-24,thu,100,from-csv\n",
                         encoding="utf-8")
    monkeypatch.delenv("ACCOUNTING_SHEET_ID", raising=False)
    monkeypatch.setenv("ACCOUNTING_LEDGER_CSV_PATH", str(csv_path))
    rows = AccountingToolProvider().read("cashflow-weekly", None, None)
    assert rows is not None and rows[0].description == "from-csv"


# --- analyzers: pure functions, THIẾU sentinel on degrade ---


def test_build_cashflow_weekly_aggregates_income_expense():
    from domain_pack_accounting.analyzers import build_cashflow_weekly
    from domain_pack_accounting.tools import LedgerRow

    rows = [
        LedgerRow("2026-08-24", "income", 1000.0, "sale"),
        LedgerRow("2026-08-25", "expense", 300.0, "supplies"),
        LedgerRow("2026-08-26", "unknown", 50.0, "?"),
    ]
    report = build_cashflow_weekly(rows)
    assert report.available is True
    assert report.total_income == 1000.0
    assert report.total_expense == 300.0
    assert report.net == 700.0
    assert report.unclassified_count == 1
    assert report.entry_count == 3


def test_build_cashflow_weekly_none_is_degraded():
    from domain_pack_accounting.analyzers import build_cashflow_weekly

    report = build_cashflow_weekly(None)
    assert report.available is False
    assert report.total_income == 0.0
    assert report.total_expense == 0.0


def test_build_cashflow_weekly_empty_list_is_not_degraded():
    from domain_pack_accounting.analyzers import build_cashflow_weekly

    report = build_cashflow_weekly([])
    assert report.available is True
    assert report.entry_count == 0


def test_render_cashflow_weekly_text_degraded_shows_thieu():
    from domain_pack_accounting.analyzers import (
        THIEU,
        build_cashflow_weekly,
        render_cashflow_weekly_text,
    )

    report = build_cashflow_weekly(None)
    text = render_cashflow_weekly_text(report, "2026-08-30")
    assert THIEU in text
    assert text.count(THIEU) == 3  # thu + chi + chênh lệch, never fabricated


def test_render_cashflow_weekly_text_happy_path_no_thieu():
    from domain_pack_accounting.analyzers import (
        THIEU,
        build_cashflow_weekly,
        render_cashflow_weekly_text,
    )
    from domain_pack_accounting.tools import LedgerRow

    report = build_cashflow_weekly([LedgerRow("2026-08-24", "income", 1000.0, "sale")])
    text = render_cashflow_weekly_text(report, "2026-08-30")
    assert THIEU not in text
    assert "1,000.00" in text


# --- offline end-to-end graph run ---


class _FakeAccountingTools:
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


def test_cashflow_weekly_graph_offline_dry_run_delivers_to_telegram(tmp_path):
    from domain_pack_accounting.tools import LedgerRow

    pack = PackRegistry().load("accounting")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": True})
    graph = pack.report_kinds["cashflow-weekly"](
        None, config=_config(True), settings=settings,
        tools=_FakeAccountingTools([LedgerRow("2026-08-24", "income", 1000.0, "sale")]),
    )
    result = graph.invoke({})
    assert result["delivered"] is True
    assert result["delivery_summary"] == "telegram=dry_run"
    assert "1,000.00" in result["report_text"]


def test_cashflow_weekly_graph_degraded_source_renders_thieu(tmp_path):
    pack = PackRegistry().load("accounting")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": True})
    graph = pack.report_kinds["cashflow-weekly"](
        None, config=_config(True), settings=settings, tools=_FakeAccountingTools(None),
    )
    result = graph.invoke({})
    assert "THIẾU" in result["report_text"]


def test_cashflow_weekly_graph_without_telegram_skips_loudly(tmp_path):
    pack = PackRegistry().load("accounting")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": True})
    graph = pack.report_kinds["cashflow-weekly"](
        None, config=_config(False), settings=settings, tools=_FakeAccountingTools([]),
    )
    result = graph.invoke({})
    assert result["delivered"] is False
    assert result["delivery_summary"] == "telegram=not_configured"


def test_cashflow_weekly_graph_rejects_external_audience(tmp_path):
    pack = PackRegistry().load("accounting")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": True})
    with pytest.raises(ValueError, match="internal"):
        pack.report_kinds["cashflow-weekly"](
            None, config=_config(True), settings=settings, audience="external",
            tools=_FakeAccountingTools([]),
        )


# --- append_ledger_row: pinned sheet + guarded-by-default write ---


def test_append_ledger_row_args_pin_configured_sheet(monkeypatch):
    monkeypatch.setenv("ACCOUNTING_SHEET_ID", "PINNED_LEDGER_SHEET")
    build = PackRegistry().load("accounting").commands["append_ledger_row"]["build_args"]
    payload = build({"values": "2026-08-24,chi,150000,Mua VPP"}, config=object())
    assert payload["argv"][:4] == ["sheets", "+append", "--spreadsheet", "PINNED_LEDGER_SHEET"]
    assert payload["argv"][4:] == ["--values", "2026-08-24,chi,150000,Mua VPP"]
    assert payload["dedup_hint"].startswith("ledger-append:2026-08-24,chi,150000,Mua VPP:")


def test_append_ledger_row_args_raises_when_sheet_not_configured(monkeypatch):
    monkeypatch.delenv("ACCOUNTING_SHEET_ID", raising=False)
    build = PackRegistry().load("accounting").commands["append_ledger_row"]["build_args"]
    with pytest.raises(ValueError, match="chưa cấu hình"):
        build({"values": "2026-08-24,chi,1,x"}, config=object())


def test_append_ledger_row_is_guarded_by_default_via_gateway(tmp_path, monkeypatch):
    """The command produces a `gws_write` action with an allowlisted 3-prefix
    (`sheets +append`) argv — same hard_block table hr-pack's append_sheet_row uses,
    no core change needed. Guarded trust_mode queues for approval; it must NEVER
    auto-execute (purge/write parity: destructive/mutating ops need explicit approval)."""
    monkeypatch.setenv("ACCOUNTING_SHEET_ID", "PINNED_LEDGER_SHEET")
    build = PackRegistry().load("accounting").commands["append_ledger_row"]["build_args"]
    payload = build({"values": "2026-08-24,thu,1,x"}, config=object())
    action = {"type": "gws_write", **payload}

    settings = build_settings_from_dict(
        {"data_dir": tmp_path, "dry_run": False, "monthly_budget_usd": 50.0,
         "trust_mode": "guarded"}
    )
    gw = ActionGateway(settings)
    try:
        result = gw.execute(action, handler=lambda a: "should-not-run-yet")
        assert result.status == "pending_approval"
    finally:
        gw.close()
