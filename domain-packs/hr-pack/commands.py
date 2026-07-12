"""hr-pack chat-command catalog (v31 P4).

Google Sheets/Docs writes via the native `gws_write` type — the write counterpart of
this pack's gws READ adapter (tools._gws_sheet_rows). The spreadsheet target is PINNED
to the agent's own configured sheet (HR_SHEET_ID env, same source the read path uses):
a requester cannot point the append at another spreadsheet. Docs commands take ids
explicitly (docs have no per-agent binding). All three run through the gateway's fixed
3-prefix table (`hard_block._GWS_ALLOWLIST_PREFIXES`) — anything else is Lớp A.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

#: Same env the hr-pack READ adapter uses (tools._SHEET_ID_ENV) — one binding source.
_SHEET_ID_ENV = "HR_SHEET_ID"


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


def _append_sheet_args(args: dict[str, str], config: Any) -> dict[str, Any]:
    sheet_id = os.environ.get(_SHEET_ID_ENV, "").strip()
    if not sheet_id:
        raise ValueError(f"chưa cấu hình {_SHEET_ID_ENV} — không biết ghi vào sheet nào")
    values = args["values"]
    return {
        "argv": ["sheets", "+append", "--spreadsheet", sheet_id, "--values", values],
        "dedup_hint": f"sheet-append:{values[:80]}:{_stamp()}",
    }


def _create_doc_args(args: dict[str, str], config: Any) -> dict[str, Any]:
    import json

    title = args["title"]
    return {
        "argv": ["docs", "documents", "create", "--json", json.dumps({"title": title})],
        "dedup_hint": f"doc-create:{title[:80]}:{_stamp()}",
    }


def _write_doc_args(args: dict[str, str], config: Any) -> dict[str, Any]:
    return {
        "argv": ["docs", "+write", "--document", args["document_id"],
                 "--text", args["text"]],
        "dedup_hint": f"doc-write:{args['document_id']}:{args['text'][:60]}:{_stamp()}",
    }


COMMANDS: dict[str, dict] = {
    "append_sheet_row": {
        "description": (
            "Thêm một dòng vào Google Sheet của agent (sheet đã cấu hình sẵn — không "
            "chọn sheet khác được). args: values (các ô cách nhau bởi dấu phẩy, vd "
            "'Nguyễn Văn A,Kế toán,2026-08-01')"
        ),
        "type": "gws_write",
        "args_schema": {
            "values": {"required": True, "max_len": 500},
        },
        "build_args": _append_sheet_args,
    },
    "create_doc": {
        "description": (
            "Tạo một Google Doc mới (rỗng — muốn có nội dung thì dùng tiếp lệnh ghi "
            "doc). args: title (tiêu đề tài liệu)"
        ),
        "type": "gws_write",
        "args_schema": {
            "title": {"required": True, "max_len": 200},
        },
        "build_args": _create_doc_args,
    },
    "write_doc": {
        "description": (
            "Ghi thêm văn bản vào cuối một Google Doc. args: document_id (mã tài "
            "liệu), text (nội dung cần ghi)"
        ),
        "type": "gws_write",
        "args_schema": {
            "document_id": {"required": True, "max_len": 100,
                            "pattern": r"[A-Za-z0-9_-]+"},
            "text": {"required": True, "max_len": 4000},
        },
        "build_args": _write_doc_args,
    },
}
