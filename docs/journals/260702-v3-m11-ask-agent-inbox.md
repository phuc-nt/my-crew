# v3 M11 — Ask-agent Slack inbox (hỏi-đáp ad-hoc)
2026-07-02 · ✅ Done

Agent giờ là "đồng nghiệp" hỏi được: mention `@<agent-id>` trong channel Slack nó phụ trách → nó đọc dữ liệu thật → trả lời trong thread. Trước M11 agent chỉ phát báo cáo một chiều theo lịch — mảnh cuối của gap "thay human hành chính" (human PM/HR bị hỏi ad-hoc hằng ngày).

## Làm gì
- **Config opt-in** `inbox: {channel, poll_minutes}` trong profile.yaml — vắng = tắt, byte-identical. **Internal-only, chặt hơn plan gốc**: channel external bị từ chối ngay lúc load (prompt QA inject persona/project/memory — nội dung internal-only không được rơi vào kênh stakeholder; Q&A external defer).
- **Poller** (`src/runtime/inbox.py`): browser-token Slack không có bot user → mention = plain-text `@<id>`, tìm qua MCP `search_messages` `in:<channel> "@<id>" after:<watermark-date>`. Watermark ts atomic ở `.data/agents/<id>/inbox_state.json`; **bootstrap không trả lời backlog** (bật agent giữa trưa không được dội một tháng mention cũ); cap 3 reply/poll; lỗi **infra** (provider/budget/network) giữ watermark để retry, lỗi **theo-message** thì skip có log (poison message không kẹt queue mãi); kill-switch bỏ poll trước khi đốt LLM.
- **QA pipeline** (`src/agent/qa_answer.py`, KHÔNG LangGraph — không cần checkpoint, gateway tự enqueue Lớp B): ground = `pack.tools.read(primary_kind)` (Protocol M5; **pm-pack THÊM `read()`** trả open issues+PRs — sửa pack, 0 domain logic vào core; hr-pack có sẵn) → snapshot JSON chặn 6k ký tự → LLM (prompt cứng: chỉ dùng DATA, không bịa số, từ chối yêu cầu hành động, câu hỏi là untrusted) → **reply qua Action Gateway** (post_message allowlisted, Lớp A, dry-run, dedup key = ts của mention → restart/re-poll không bao giờ double-reply).
- **Wire**: worker nhận kind `inbox` (0 mention = thành công, khác report); service tổng hợp cron `*/N` từ poll_minutes vào đúng một đường scheduler sẵn có; `mpm agent run <id> --report inbox` chạy tay được.

## Review (DONE_WITH_CONCERNS → vá hết trong milestone)
- **H1 (đắt giá): self-loop guard chỉ nằm ở docstring.** Search index cả thread reply; nếu LLM echo `"@<id>"` trong câu trả lời ("@x làm gì?" → "…@x là…"), poll sau match chính reply đó (ts mới → dedup vô hiệu) → vòng lặp trả lời chính mình vô hạn. Vá **structural**: `sanitize_reply` strip mention phrase (case-insensitive) + vô hiệu `<!channel>/<!here>` trước khi post; test dùng LLM stub CỐ TÌNH echo. Bài học: bất biến chống-loop phải nằm ở code, không phải ở prompt hay docstring.
- **M1** search không giới hạn thời gian → channel già đầy mention cũ đẩy mention mới khỏi top-20 → inbox "điếc dần" → vá `after:` theo watermark (overlap 1 ngày).
- **M2** lỗi hạ tầng bị xử như poison → câu hỏi của người dùng biến mất im lặng → vá phân loại infra-vs-message + kill-switch bỏ poll.
- L1 case-insensitive match, L2/L3 state file bền, L4 thread-root ts, L5 1 gateway/poll, L8 chặn broadcast injection.

## Lằn ranh đỏ — VERIFIED
Write DUY NHẤT trên toàn path = 1 reply qua gateway (search/list là READ như jira_read). Mention text vào user-role only; LLM output chỉ là TEXT của reply — không có tool nào khác với tới (default-DENY). Prompt injection tệ nhất = nội dung reply xấu trong channel internal, không phải hành động.

## Verified
909 pytest (24 mới) + ruff clean. **E2E live**: post `@default team đang có bao nhiêu PR mở?…` vào channel internal thật → poll → reply thật trong thread ts=1782966248: "Team hiện có **2 PR mở**, cả 2 stale **10 ngày**…" đúng dữ liệu GitHub thật; re-poll → `no_mentions` (không double); bootstrap bỏ qua mention cũ đúng thiết kế; dry_run compose nhưng không post (yaml dry_run thắng env — đúng ngữ nghĩa explicit-wins).

## Bài học
- Slack browser-token không có bot identity → mention convention phải là plain-text; và vì search index thread reply, chống self-loop bằng nội dung (strip phrase) chắc hơn chống bằng danh tính.
- "Skip lỗi để queue chạy tiếp" cần phân loại lỗi: poison-message skip là đúng, provider-outage skip là mất tin nhắn người dùng.
- Reuse một đường scheduler (synthesize cron ảo) rẻ và ít bug hơn viết poll loop thứ hai.
