# Phase 1 Slice 2 — Confluence detail + Slack short+link

2026-06-22 · ✅ E2E xong (post thật Confluence + Slack)

## Làm gì
- Đổi luồng deliver: report **detail (XHTML storage) lên Confluence** (page mới/ngày, space MPM) → **short report + link lên Slack** qua Action Gateway.
- `confluence_write.py`: `create_report_page` Handler qua gateway (allowlist đã có `confluence:createPage`), parse page id + URL từ response text-block, dedup per (space, ngày).
- `report_prompt.py`: `build_detail_messages` (XHTML), `build_slack_short` (mrkdwn, dẫn xuất từ risks — không LLM lần 2).
- `report_graph.py`: deliver 2 bước (Confluence trước → Slack short+link).
- E2E thật: page Confluence id 131294 + Slack post #report (link clickable). 130 UT pass, ruff clean.

## Quyết định & vì sao
| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Confluence page mới mỗi ngày | Có lịch sử từng ngày, đơn giản hơn updatePage (cần version) | Nhiều page dần |
| 1 LLM call detail, short dẫn xuất code | Tiết kiệm token, short không cần creativity | Short kém "tự nhiên" hơn |
| State chỉ giữ primitive (risks=dict) | Checkpointer chặn deserialize dataclass lạ (langgraph strict msgpack) | Model nặng giữ trong closure graph, không qua state |

## Vấp & học được
- Verify MCP với server thật lộ nhiều lệch shape (đúng cảnh báo training-data cũ): `getSpaces`/`createPage` trả **text-block người-đọc** (không JSON) → parse text + tự dựng URL từ relative path.
- Slack browser-token **khóa cứng workspace** (xoxc segment): token sai workspace → list nhầm channel + post `channel_not_found`. Phải lấy token đúng workspace MPM.
- 2 MCP server (jira/slack) log ra **stdout** làm hỏng JSON-RPC → hotfix log→stderr (commit ở repo server). Confluence server đã đúng (stderr).
- Slack KHÔNG dùng GitHub-markdown → sửa prompt sang Slack mrkdwn (`*đậm*`, `•`); bỏ bug LLM tự chèn `$(date)` placeholder bằng cách truyền ngày thật.

## Mở / sang sau
- Gateway dedup in-memory → re-arm sau restart (xử lý khi có cron/retry).
- Slice tiếp: template daily/weekly, cron entrypoint, burndown.
- Page probe rác (id 131273/131294) — xóa tay nếu cần (deletePage là Lớp A hard-block, agent không tự xóa).
