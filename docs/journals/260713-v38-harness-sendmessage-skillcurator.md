# v38 — Harness enhancement wave 1: send_message + skill-curator
2026-07-13 · ✅ Done (2177 BE)

TOP-2 gap từ research `harness-enhancement-suggestions-v37.md` (đối chiếu OpenClaw/Hermes). CEO chốt đợt 1 = #1+#2 (loại #3 local-model). Cả 2 làm giàu harness, invariant sạch.

## Làm gì
- **#1 send_message**: primitive "chủ động gửi X tới kênh/người Y". FACADE ánh xạ `{channel, to, text}` → writer per-channel đã có (slack/telegram/email) — mỗi writer đã gọi gateway → thừa hưởng Lớp A/B + trust_mode + audit + dedup. Surface = chat-ops catalog command (LLM điền slot, CODE gọi facade qua gateway coordinator). KHÔNG là tool LLM-callable trong read-only loop (giữ moat).
- **#2 skill-curator**: `record_usage` đếm skill được `skill_selector` chọn (per-agent sidecar, best-effort) + archive sweep chuyển skill agent-own quá hạn (90d unused / 30d never-used) sang `skills/.archive/` (không xoá). Chỉ agent-own — template-role skill (v36 live-load) không đụng. Wire vào service hygiene 3h sáng, cooldown 24h.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Facade, KHÔNG action-type gateway mới | Reuse writer đã gọi gateway → 0 guard mới, không nhân đôi classify/dispatch | — |
| send_message qua chat-ops, KHÔNG qua read-only loop | Tool ghi trong LLM loop = phá moat (LLM tự gửi tuỳ ý). Catalog=code (LLM điền slot) an toàn theo pattern M14 | Agent không "tự phát" gửi — phải qua CEO/coordinator |
| Slack recipient ALLOWLIST (review HIGH #2, CEO chốt) | Slack `to` trước denylist-only → kênh lạ auto-execute cho autonomous. Giờ chỉ report/external channel đã cấu hình | Kênh mới phải đăng ký trước |
| audience field CẮT (CEO chốt) | send_message = CEO gửi text cụ thể (không phải agent compose từ internal) → audience-gate không cần | — |
| skill archive chỉ MOVE (không xoá) + cooldown | user-data, khôi phục tay; cooldown 24h chống re-glob 60×/giờ (mirror memory consolidation) | — |

## Vấp & học được
- **Review Sonnet bắt 2 HIGH thật**: (1) reply "Đã gửi" cho cả dedup/skip (CEO tưởng gửi mà thực ra trùng bị bỏ) → phân nhánh theo `GatewayResult.status` trung thực; (2) Slack denylist-only (telegram có allowlist, email luôn Lớp B, riêng slack hở) → thêm allowlist. Cả 2 là code-review đọc source, không đoán.
- Threat-model rule: allowlist Slack là tradeoff bảo mật → HỎI CEO (không tự vá), CEO chốt thêm allowlist.
- ProfileContext gain `agent_id` optional (set 1 chỗ ở worker) → skill-usage tracking flow mọi caller free, không đổi signature `select_skill_text` cho từng graph (DRY).
- Flaky live test `test_create_agent_recursion_live` (recursion rounds phi định) — pass khi chạy riêng, bỏ qua.

## Mở / sang sau
- Đợt 2 research: #4 OSV-scan (điều kiện mở community) → #3 multi-provider. Đợt 3: #5 background-review, #6 write-back memory (đụng invariant nhạy).
- send_message hiện chỉ chat-ops surface; nếu sau cần agent tự-phát gửi (team-step egress mở rộng) thì thêm đường code-path riêng, vẫn qua gateway.
