# v41 — deep_agent lease + artifact read-back + create_agent docs
2026-07-14 · ✅ Done (2242 BE)

Benchmark-lại (sau vá file-write v40) xác nhận 0/4 crash write NHƯNG lộ bug kế tiếp: deep_agent 565-612s đụng trần container-lease 600s cứng → 2/4 run chết. Vá + 2 việc bổ trợ.

## Làm gì
- **P1 lease cấu hình được**: container `sleep 600` → `sleep {lease}` (hằng `SANDBOX_LEASE_S=1800`, cap 3600, config qua `sandbox: {lease_seconds}`). Reaper orphan-threshold = **max(step-lease 600, sandbox-lease 1800)** → container hợp lệ >600s KHÔNG bị reap (bug 2/4 run). deep_agent 565-612s giờ vừa lease.
- **P2 read-back artifact**: `_merge_sandbox_artifacts` đọc `/work/*.md` agent ghi → gắn vào result_text TRƯỚC teardown (report không mất khi agent ghi file rồi container bị dọn). Best-effort, cap 256KB, skip trùng/binary.
- **P3 docs**: deployment-guide §6a — khi nào/cách bật `create_agent`/`deep_agent` (+ `lease_seconds`), giữ **native default** (CEO chốt). 0-code core (config đã validate); KHÔNG đổi template nào.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Đặt `SANDBOX_LEASE_S` ở sandbox_backend, KHÔNG đổi `DEFAULT_LEASE_TTL_S` | 2 khái niệm KHÁC nhau: DEFAULT_LEASE_TTL_S = lease worker team-step (re-reserve), sandbox-lease = đời container. Report gộp vì cùng 600 — thực ra riêng | Reaper phải lấy max(2 lease) |
| Reaper threshold = max(step, sandbox lease) | Container hợp lệ sống tới 1800s (self-terminate) — reaper chỉ dọn orphan worker-chết vượt CẢ 2 lease + grace | — |
| lease default 1800 cap 3600 | CEO chốt — an toàn deep_agent chậm, cap chống run-kẹt giữ container mãi | Container sống lâu hơn (moat isolation KHÔNG nới) |
| deep_agent trả text + read-back artifact | Report hay ghi file; đọc lại trước teardown giữ report | Cap size + best-effort |
| Giữ native default, chỉ doc create_agent | native rẻ/xác định cho report template; create_agent opt-in cho reasoning mở | — |

## Vấp & học được
- **Report gộp 2 khái niệm lease** (step-worker-lease vs sandbox-container-lease đều 600). Đọc code phân biệt: đổi DEFAULT_LEASE_TTL_S sẽ SAI (đụng re-reserve worker). → đặt hằng riêng + reaper lấy max. Bài học: benchmark chỉ đúng-hướng, phải verify semantic trên code trước khi làm.
- **Real Docker E2E xác nhận** container cmd `['sleep','1800']` — bug (auto_remove 600s giữa run) đã hết.
- Self-review reaper math: threshold 1980s → container ≤1800 không reap, orphan >1980 reap, vẫn label-gated. Không false-reap, không miss-orphan.

## Mở / sang sau
- Lease heartbeat (gia hạn theo tiến độ) cho task RẤT dài — hoãn (1800/3600 đủ hiện tại).
- cost_cap hard-stop, stall-detect — hoãn (recursion cap + coordinator per-task cap đủ).
