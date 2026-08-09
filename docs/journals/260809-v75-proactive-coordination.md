# v75 — Coordination chủ động (học chọn lọc từ Hermes/OpenClaw)
2026-08-09 · ✅ Done

## Làm gì
- Brainstorm đối chiếu coordination core với OpenClaw/Hermes (khảo sát file-level) +
  landscape 2026 (web): kiến trúc my-crew khớp pattern thắng thế, hơn 2 harness kia về
  đội-làm-việc first-class — không đổi kiến trúc, mượn 3 cơ chế có đảo chiều an toàn.
- **F-bundle**: wake-context line theo attempt (kênh guidance); `web_search_outcome`
  tách "web nói không có" ≠ "không tới được web" → sentinel 3-path ở CẢ native hook
  lẫn tool-loop `web.search`; watcher tick toàn lỗi trả `all_polls_failed` thay vì
  `no_change`.
- **Goal-replan** (bản my-crew của Hermes `/goal`, đảo fail-open → fail-CLOSED):
  autopilot ladder 2→3 rung — retry → **replan bằng amend-LLM qua đúng flow
  amend+hash** (identity proposal/LLM lỗi/không còn bước chờ = từ chối, stall đứng
  nguyên) → accept/drop.
- **Hybrid collect launcher** (pattern Hermes): code prefetch 1-3 query (title +
  biến thể topic+entity, không LLM call) qua đúng WebSearchConfig+audit → bundle
  inject vào slot search-hook native → bước collect thoát tool-loop; fail-open về
  đường cũ.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Judge/replan fail-CLOSED, đi qua amend+hash sẵn có | my-crew có quyền ghi thật (Hermes fail-open an toàn chỉ vì use-case search-only) | Bế tắc thật vẫn chờ CEO — chấp nhận |
| Prefetch ở runner, route native qua param `prefetched` | Không nới quyền, không đổi graph; hint-only tự hồi phục giữ nguyên | Query heuristic không hoàn hảo — fail-open bù |
| Không copy heartbeat self-schedule của OpenClaw | Khung đó chết trong thực tế (mọi HEARTBEAT.md rỗng) — nhịp chủ động phải gắn queue thật | — |

## Kiểm chứng sống (data thật, cùng ngày)
- Zetakron (thực thể bịa): chuỗi ghi "THIẾU DỮ LIỆU" không bịa, delivered.
- `fanout_gap` cưỡng bức tách 2/2 lần đề un-fanned; split-sub thừa kế `needs_web`
  chạy sống lần đầu (3 sub đều web=1).
- Prefetch: audit 2 query liền nhau đúng shape derive_queries → collect native
  **119s, gap 2s** (vs 199–425s tool-loop trước).
- Ladder: task gave_up (Webex) → rung 1 reset → hoàn thành đủ 5/5 dịch vụ, done,
  $0.074. Rung 2 goal-replan chưa gặp ca sống (unit-test đủ 4 nhánh).

## Vấp & học được
- Sentinel chỉ vá native hook là chưa đủ — tool-loop có `web.search` RIÊNG cùng bệnh;
  flag/contract mới phải rà MỌI tier (bài học lặp lại từ vụ mint-row v74).
- Test cũ patch `web_search` thành inert khi code chuyển sang `web_search_outcome`
  → test đánh HTTP thật với key giả; đổi API nhớ rà chỗ patch.
- Nâng `MAX_AUTOPILOT_ATTEMPTS` mở rung mới cho cả task stalled CŨ trong store —
  vô hại (refusal) nhưng đáng nhớ khi nâng trần bất kỳ ladder nào.

## Ca sống goal-replan (trưa 09/08, staged task v75replan01)
- Dựng task stalled với bước chết + ap=1 (mô phỏng retry đã tiêu) → tick kế **rung 2
  bắn thật**: amend LLM thay 1 bước chết bằng 5 bước mới (3 research song song giao 3
  người khác + verify + synthesize), confirm hash thật, reopen, chạy đến **done +
  delivered ($0.032)**; rung 3 drop dọn bước chết cũ bằng placeholder trung thực
  ("chủ động bỏ qua"); bản chốt giữ nguyên cảnh báo toàn vẹn, không bịa.
- Ca sống lộ ngay bug lặp bài học 112033f lần 3: **schema ví dụ amend thiếu toàn bộ
  flags + acceptance** → 5 bước mới đều needs_web=0. Vá 947412f (example schema mang
  acceptance + 4 cờ, pin test). Ba đường mint bước (decompose/split/amend) giờ đều
  qua bài kiểm "flag nằm trong ví dụ".

## Mở / sang sau
- Prefetch mới phủ native-route; bước bị can thiệp quay lại tool-loop có thể prefetch
  bổ sung — xem sau khi có số.
- Tailscale (2 thao tác phía CEO) vẫn pending.
