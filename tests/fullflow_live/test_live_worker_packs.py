"""Nhóm H — worker packs Accounting/Ads (P6) chạy qua ĐỒ THỊ THẬT với model thật.

Điều mà suite offline không đo được: hai graph này gọi model thật ở node `_narrate` để
viết câu nhận xét cho chủ doanh nghiệp, và cái nguy hiểm nhất ở đó là model được đưa
những con số đã tính sẵn kèm mệnh lệnh "không tự bịa số khác". Với model script, mệnh
lệnh đó chưa từng bị thử. Ở đây nó bị thử thật:

  - H1: nguồn hỏng → `available=False` → bảng số phải là THIẾU. Model vẫn được gọi để
    viết narrative, nên đây chính là chỗ nó có thể bịa ra một con số nghe hợp lý. Case
    assert rằng KHÔNG có chữ số nào xuất hiện trong phần narrative.
  - H2: nguồn thật (file CSV thật trên đĩa) → số trong báo cáo phải khớp CHÍNH XÁC với
    số tự cộng tay, bất kể model viết gì.

H1 cũng là lưới regression cho C1: trước bản vá, một credential hỏng ném
`CredentialDecryptError` xuyên qua `perceive` và làm sập cả `graph.invoke`, thay vì
degrade thành THIẾU. Case chạy qua graph thật chứ không qua ToolProvider giả — đó là
đúng đường mà lỗi C1 đi.
"""

from __future__ import annotations

import dataclasses
import re

import pytest

from my_crew.config.config_builders import (
    build_reporting_config_from_dict,
    build_settings_from_dict,
)
from my_crew.config.telegram_config import TelegramConfig


def _report_config():
    """Config có Telegram nhưng token trỏ vào env var KHÔNG được đặt.

    Cố ý: node `deliver` sẽ đi tới cổng gửi thật, và vì đây là `dry_run=True` cộng với
    token vắng mặt, không có tin nhắn nào rời khỏi tiến trình. Một bộ test không được
    nhắn cho ai chỉ để chứng minh nó tính đúng."""
    config = build_reporting_config_from_dict(
        {"jira_project_key": "X", "github_repo": "o/r", "slack_report_channel": "C_TK",
         "slack_stakeholder_channel": "", "slack_external_channels": ""}
    )
    telegram = TelegramConfig(
        bot_token_env="FULLFLOW_LIVE_ABSENT_BOT_TOKEN",
        chat_ids=("111",), ops_operator_id="111",
    )
    return dataclasses.replace(config, telegram=telegram)


def _live_settings(tmp_path):
    """Settings mang key thật (để `_narrate` gọi được model) nhưng `dry_run=True` để
    mọi hành động ghi-ra-ngoài dừng ở cổng."""
    from tests.fullflow_live.conftest import _ENV_SETTINGS

    return build_settings_from_dict({
        "openrouter_api_key": getattr(_ENV_SETTINGS, "openrouter_api_key", ""),
        "data_dir": tmp_path,
        "dry_run": True,
    })


def _narrative_of(report_text: str) -> str:
    """Phần model viết = mọi thứ TRƯỚC bảng số deterministic (graph nối bằng '\\n\\n')."""
    return report_text.split("\n\n", 1)[0]


# --- H1: nguồn hỏng phải ra THIẾU, và model không được bịa số -----------------------


def test_h1_a_broken_ads_credential_degrades_to_thieu_without_inventing_numbers(
    tmp_path, monkeypatch
):
    """Token Meta hỏng → báo cáo THIẾU, graph KHÔNG sập, narrative không có số.

    Hai lời hứa trong một case, và cả hai đều chỉ đo được ở đây:
      1. fail-degrade (C1): `perceive` nuốt lỗi credential thay vì ném xuyên graph.
      2. không-bịa-số: model thật nhận `available=False` và phải viết một câu không
         chứa con số nào. Đây là ràng buộc mà chỉ model thật mới kiểm chứng được.
    """
    monkeypatch.setenv("ADS_META_AD_ACCOUNT_ID", "123456789")
    # Tài khoản không tồn tại trong kho → CredentialDecryptError từ resolver. Đường
    # hỏng thật, không phải một exception được mock ra cho vừa với code.
    monkeypatch.setenv("ADS_META_TOKEN", "")

    from my_crew.packs.registry import PackRegistry

    pack = PackRegistry().load("ads")
    settings = _live_settings(tmp_path)
    graph = pack.report_kinds["ads-weekly"](
        None, config=_report_config(), settings=settings,  # tools=None ⇒ provider thật
    )
    result = graph.invoke({})

    text = result["report_text"]
    assert "THIẾU" in text, f"nguồn hỏng phải render sentinel THIẾU: {text!r}"

    narrative = _narrative_of(text)
    assert narrative.strip(), "vẫn phải có một câu nhận xét, không được rỗng"
    assert not re.search(r"\d", narrative), (
        "narrative của một báo cáo THIẾU không được chứa con số nào — có số nghĩa là "
        f"model đã bịa ra dữ liệu không tồn tại: {narrative!r}"
    )


def test_h2_a_missing_data_source_is_loud_not_degraded(tmp_path, monkeypatch):
    """Chưa cấu hình nguồn là lỗi NGƯỜI DÙNG — phải kêu to, không được degrade âm thầm.

    Khác biệt cố ý với H1: "API gọi hỏng" thì degrade, còn "chưa cấu hình gì cả" thì
    nổ. Gộp hai cái này lại sẽ khiến một fleet quên cấu hình nhận báo cáo THIẾU đều đặn
    mỗi tuần mà tưởng là Meta đang lỗi. Không gọi model."""
    monkeypatch.delenv("ADS_META_AD_ACCOUNT_ID", raising=False)

    from my_crew.packs.registry import PackRegistry

    pack = PackRegistry().load("ads")
    graph = pack.report_kinds["ads-weekly"](
        None, config=_report_config(), settings=_live_settings(tmp_path),
    )
    with pytest.raises(RuntimeError, match="ADS_META_AD_ACCOUNT_ID"):
        graph.invoke({})


# --- H3: dữ liệu thật, số phải khớp tuyệt đối ---------------------------------------


def test_h3_the_accounting_report_numbers_match_the_real_ledger_file(tmp_path, monkeypatch):
    """Sổ quỹ CSV thật trên đĩa → số trong báo cáo khớp chính xác số cộng tay.

    Model được gọi để viết narrative, nhưng bảng số là deterministic — nên case này
    chứng minh đúng cái ranh giới mà kiến trúc pack dựa vào: model được viết chữ, KHÔNG
    được động vào số. Nếu ai đó sau này để model tính hộ, case này đỏ."""
    ledger = tmp_path / "so-quy.csv"
    ledger.write_text(
        "date,type,amount,description\n"
        "2026-08-24,thu,15000000,Thanh toán hợp đồng A\n"
        "2026-08-25,chi,4500000,Tiền thuê văn phòng\n"
        "2026-08-26,chi,1200000,Mua văn phòng phẩm\n"
        "2026-08-27,thu,3000000,Khách lẻ\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ACCOUNTING_SHEET_ID", raising=False)
    monkeypatch.setenv("ACCOUNTING_LEDGER_CSV_PATH", str(ledger))

    from my_crew.packs.registry import PackRegistry

    pack = PackRegistry().load("accounting")
    graph = pack.report_kinds["cashflow-weekly"](
        None, config=_report_config(), settings=_live_settings(tmp_path),
    )
    result = graph.invoke({})

    text = result["report_text"]
    assert "THIẾU" not in text, f"nguồn đọc được thì không được render THIẾU: {text!r}"

    from domain_pack_accounting.analyzers import build_cashflow_weekly
    from domain_pack_accounting.tools import TOOL_PROVIDER

    report = build_cashflow_weekly(TOOL_PROVIDER.read("cashflow-weekly", None, None))
    assert report.total_income == 18000000.0, report
    assert report.total_expense == 5700000.0, report
    assert report.net == 12300000.0, report
    assert report.entry_count == 4, report

    # Bảng số trong báo cáo phải mang đúng những con số này (định dạng có thể khác,
    # nên so trên chuỗi đã bỏ dấu phân cách nhóm).
    normalized = text.replace(",", "").replace(".", "").replace(" ", "")
    for number in ("18000000", "5700000", "12300000"):
        assert number in normalized, (
            f"số {number} phải xuất hiện trong báo cáo — bảng số là deterministic, "
            f"không phụ thuộc model: {text!r}"
        )
