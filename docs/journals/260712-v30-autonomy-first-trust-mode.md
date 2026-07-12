# v30 — Autonomy-first: trust_mode autonomous mặc định, guarded opt-in
2026-07-12 · COOKED (1894 BE + 180 FE, UAT live 4/4)

## Làm gì
- Pivot định hướng: `Settings.trust_mode` — **autonomous mặc định** (Lớp B/allowlist-miss có handler chạy NGAY + audit hằng số `AUTONOMOUS_RATIONALE`), `guarded` = hành vi cũ nguyên vẹn. Global `TRUST_MODE` env + per-agent `safety.trust_mode` (yaml thắng env).
- 2 điểm cưỡng chế gateway (`_execute`, `enqueue_for_approval` — chat flatten mọi sender theo quyết định CEO) + `approval_gate` nhận settings (None ⇒ guarded fail-safe) wire 3 report graph.
- Surface: wizard "Chế độ hành động", agents API expose effective mode, AgentPage badge, chat reply phân biệt tự-chủ/dedup/dry-run.
- Docs 9 file reposition autonomy-first + 5 disclosure (chat flatten, fleet-flip, no daily-cap, dry_run độc lập, propose-only vẫn queue).

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Giữ 1 cửa gateway, flip policy (không bypass) | Giữ audit/cost/observability; guarded = tập con không viết lại | Vẫn còn overhead classify mỗi action (không đáng kể) |
| Lớp A bất khả xâm cả 2 mode | Thảm họa không-đảo-ngược; gần như không cản việc thường | — |
| Chat flatten (mọi sender chạy ngay khi autonomous) | CEO chốt tường minh sau red-team cảnh báo injection | Gate còn lại là reachability (chat allowlist/channel) |
| Fleet-flip khi upgrade + không daily-cap | Đúng tinh thần pivot; backstop = cap $2/task + timeout + kill-switch + dedup | hr/admin gửi thật không chờ duyệt — release note |
| Propose-only (handler=None) vẫn queue | Không có carve-out này automation proposal bị nuốt im lặng | Duyệt tab vẫn có việc kể cả fleet autonomous |

## Vấp & học được
- **Red-team bắt 2 claim sai trước khi code:** "1 điểm pin conftest, flip 4 file" sai cả 2 chiều (33 file gọi builder trực tiếp, ≥8 assert pending); nhánh autonomous thiếu carve-out `handler=None` sẽ nuốt proposal. Lần thứ 4 liên tiếp red-team-trước-cook trả giá trị.
- **Docs-subagent overclaim + bịa:** viết "self-approved" thay hằng số thật, "allowlist unchanged" (sai — autonomous pass-with-audit), và chèn `trust_mode` vào closed-ENUM PII không tồn tại. Phải grep-verify sau mọi docs delegation.
- E2E không idempotent trong ngày (bài học v17 lặp lại): guarded resume trả `deduplicated` vì trùng nội dung run autonomous trước đó — chính lưới dedup chứng minh mình hoạt động.

## Mở / sang sau
- Wizard M17 chưa ghi `TRUST_MODE` vào .env lúc setup (env-doc đủ cho v30).
- Nếu cần daily-write-cap cho autonomous: hook sẵn `claim_daily_slot`.
