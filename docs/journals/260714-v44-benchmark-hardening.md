# v44 — benchmark-hardening wave (429 backoff + configs + routing doc)
2026-07-14 · ✅ Done (2290 BE)

Benchmark tri-harness HARD-v3 (MPM vs OpenClaw vs Hermes, run thật qwen3.7) map điểm kém MPM. Triage: phần lớn "điểm kém" là MOAT (sandbox always-on, hard caps) lộ ra vì task benchmark lệch sân (research-1-agent-speed, không phải PM/HR/admin). Wave này làm subset đúng-identity: 1 điểm robustness thật + 2 config-hardening (giữ default) + 1 doc.

## Làm gì
- **W3 (anchor) — 429 backoff**: linear 1.5s→3s / 2 retry / không jitter → **exp 1.5·2^attempt + full jitter + honor Retry-After** (clamp 30s/attempt), retry 2→4, **total-wait cap 75s** kiểm TRƯỚC sleep → không overrun lease 1800s (429 mềm không thành SIGKILL cứng). Team run đa-call retry lockstep = tự gây 429 storm; jitter de-sync.
- **W1 — mem_limit config**: hằng "512m" → per-company qua seam `lease_seconds` v41 (`_clamp_mem` [256m,4g], garbage→default). **Default 512m nguyên**, vẫn ở degradable group.
- **W2 — deep_team cap config**: `_MAX_TASK_CALLS=3` → thêm int RIÊNG `deep_team_max_calls` (4-hop seam), clamp [1,8], **default 3 nguyên**. Clause + middleware cùng 1 resolved `task_cap` (không drift).
- **Doc §6b**: decision table tier + multi-agent (native team=fan-out rộng, deep_team=siloing hẹp ≤3, create_agent=no-shell) + knob v41/v44. Fix đòn bẩy cao nhất — chữa lỗi PHÁN ĐOÁN benchmark phơi ra.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| W2: thêm int riêng, KHÔNG widen bool→union | `int 0` falsy → widen bool sinh bug truthiness; int riêng additive, gate ON/OFF sạch | 2 field thay 1 |
| Giữ MỌI default (512m/3), chỉ config | "điểm kém" là moat; benchmark lệch sân. Knob cho operator nặng hiếm; default bảo vệ ca thường + bound blast-radius | — |
| W3 total-wait cap 75s | retry stall trong sandbox step đốt lease → SIGKILL (429 mềm thành kill cứng). Cap ≪ 1800s là ràng buộc load-bearing | Bỏ cuộc sớm hơn nếu 429 kéo dài |
| W4 (chậm 1-agent) WON'T-FIX | sandbox ephemeral always-on = moat; pool phá isolation. 707s là biên lai an toàn, không phải defect | Chậm hơn OpenClaw (đúng-sân không đua tốc độ) |
| Doc là fix chính, không đổi số | benchmark thấy deep_team ROI-âm fan-out rộng — lỗi DÙNG SAI công cụ, không phải cap thấp | — |

## Vấp & học được
- **"200-tick" + concurrency-2 KHÔNG phải lỗi MPM**: verify code — 200-tick là cap driver benchmark (ticker MPM unbounded `while True`); concurrency-2 ĐÃ config per-company. Bài học: lọc benchmark-finding qua code trước khi tin.
- **Review bắt low type-coercion**: `isinstance(x, int)` True cho bool → `deep_team_max_calls: true` thành 1 ngầm; quoted "5" rơi về default im lặng. Khác posture loader (raise trên bad type). Vá: `_parse_deep_team_max_calls` raise loud (khớp `max_per_day`).
- **Retry-After verify SDK thật**: openai 2.43 — `RateLimitError` là `APIStatusError` có `.response.headers`; `APITimeoutError`/`APIConnectionError` KHÔNG. Guard `getattr(exc,"response",None)` an toàn. HTTP-date/garbage → None → fallback exp (không crash).

## Mở / sang sau
- MAX_STEPS=7 / MAX_TASK_STEPS=15 vẫn hằng (medium fix, off-anchor) — làm nếu có task PM thật cần >7 step.
- W4 pre-pull image warm (bỏ cold-pull latency, KHÔNG chạm security model) — tùy chọn nếu operator thật phàn nàn.
- Hermes kanban worker crash (không phải MPM) — đào riêng nếu Hermes là ứng viên.
