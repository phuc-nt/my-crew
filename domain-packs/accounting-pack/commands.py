"""accounting-pack chat-command catalog (P6) — the one guarded write: append_ledger_row.

Google Sheets write via the native `gws_write` type — the write counterpart of this
pack's gws READ adapter (tools._gws_sheet_rows). The spreadsheet target is PINNED to the
agent's own configured ledger sheet (ACCOUNTING_SHEET_ID env, same source the read path
uses): a requester cannot point the append at another spreadsheet. Runs through the
gateway's fixed 3-prefix table (`hard_block._GWS_ALLOWLIST_PREFIXES`, which already
allows `("sheets", "+append")`) — anything else is Lớp A.

Guarded by default: like hr-pack's append_sheet_row, this command is only reachable once
an operator has explicitly enabled it for the agent (chat-command gating happens outside
this pack, in the core command dispatch/allow config) — never wired into autopilot.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

#: Same env the accounting-pack READ adapter uses (tools._SHEET_ID_ENV) — one binding source.
_SHEET_ID_ENV = "ACCOUNTING_SHEET_ID"


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


def _append_ledger_row_args(args: dict[str, str], config: Any) -> dict[str, Any]:
    sheet_id = os.environ.get(_SHEET_ID_ENV, "").strip()
    if not sheet_id:
        raise ValueError(f"chưa cấu hình {_SHEET_ID_ENV} — không biết ghi vào sổ quỹ nào")
    values = args["values"]
    return {
        "argv": ["sheets", "+append", "--spreadsheet", sheet_id, "--values", values],
        "dedup_hint": f"ledger-append:{values[:80]}:{_stamp()}",
    }


COMMANDS: dict[str, dict] = {
    "append_ledger_row": {
        "description": (
            "Thêm một dòng vào sổ quỹ (Google Sheet đã cấu hình sẵn — không chọn "
            "sheet khác được). args: values (các ô cách nhau bởi dấu phẩy theo thứ tự "
            "date,type,amount,description — vd '2026-08-30,chi,150000,Mua văn phòng phẩm')"
        ),
        "type": "gws_write",
        "args_schema": {
            "values": {"required": True, "max_len": 500},
        },
        "build_args": _append_ledger_row_args,
    },
}
