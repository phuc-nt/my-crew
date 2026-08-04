# v64 — Vá 4 finding UAT: honest-drop, shell guard, terminal review, chống đói queue
2026-08-04 · hoàn thành

## Làm gì

- **Honest-drop**: placeholder bước-bị-bỏ thành chỉ thị cấm suy diễn + luật trung thực
  dữ liệu vào SYSTEM prompt bước làm việc và prompt aggregate (đặt ở SYSTEM vì wrapper
  nội dung coi handoff là data-không-phải-lệnh).
- **Shell guard**: `sandbox_capable_ids()` + `validate_shell_steps()` trong vòng
  decompose/amend — bước `needs_shell` không ai chạy được thì chết lúc LẬP KẾ HOẠCH
  với message rõ (vòng retry cho LLM tự bỏ cờ), hết cảnh chết-lúc-chạy → drop → bịa.
  Bật sandbox thật cho analyst (`agent_runtime: deep_agent` + Docker, user-data).
- **Terminal review policy** (CEO chốt): `apply_review_waiver` → `apply_review_policy`
  — task nhỏ nội bộ giữ 0 review; còn lại CODE quyết: chỉ bước terminal + mọi bước
  `external_write` được soát, cờ LLM chỉ là gợi ý. Amend bắt giá trị validate trả về
  (trước đây vứt — new_pending mang flag thô của model).
- **Chống đói queue**: `run_one_tick` phục vụ task chưa-từng-chạy-bước trước, còn lại
  FIFO (sort stable, 1 dòng).
- Suite 2506 BE (+7); UAT sống: guard tự lái model bỏ needs_shell khi đội chưa có
  sandbox; sau khi bật analyst → chuỗi viết-code (researcher, native) → **chạy thật
  trong Docker** (`engine=deep_agent`, 532/468 ngẫu nhiên thật) → tổng hợp giữ đúng số.

## Quyết định & vì sao

| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Chỉ review terminal + external | 2 vòng UAT: 5 bước phình 23 dòng rồi stall; review giữa chuỗi đắt hơn giá trị | Lỗi bước giữa bắt muộn 1 vòng — bù bằng self-check + review terminal |
| Guard shell ở plan-time, retry tự sửa | CEO ít khi phải thấy lỗi — model tự bỏ cờ khi đội thiếu sandbox | Không có sandbox thì task "chạy code" thành suy luận — trung thực hơn chết ngầm |
| Chống đói tối thiểu (không round-robin) | Xử đúng ca đo được (task mới đứng im 40'); round-robin đợi nhu cầu thật | Task giữa chừng vẫn có thể chờ lâu sau task bận |

## Vấp & học được

- Chuỗi nguy hiểm nhất không phải lỗi cơ chế mà là lỗi IM LẶNG: fail-closed đúng →
  autopilot drop đúng thang → bước sau bịa số liệu rất thuyết phục. Ba lớp vá phải đặt
  ở ba chỗ khác nhau (placeholder, system prompt, aggregate prompt) vì wrapper chống
  injection cố tình hạ cấp text nội dung thành data.
- `validate_decomposition` trả bản đã chuẩn hoá nhưng call-site amend vứt kết quả —
  loại bug "gọi mà không nhận" khó thấy vì mọi test đi đường assign.

## Mở / sang sau

- ~~Round-robin đầy đủ~~ — đóng cùng ngày: round-robin KHÔNG CẦN STATE — sort task theo
  "hoạt động cũ nhất trước" (max spawned_at/last_seen các bước; task chưa chạy = "" nên
  luôn đứng đầu, nuốt luôn rule chống-đói): phục vụ task nào là task đó tự bị stamp lùi
  xuống sau ở tick kế. Test pin 2 task bận luân phiên.
- ~~`_approval_status` scan cross-store~~ — đóng cùng ngày: read-path scope theo
  `assigned_to` y hệt write-path (approval id là AUTOINCREMENT per-FILE, đọc chéo store
  có thể trúng hàng của agent khác).
- Còn chờ CEO quyết: nhắc-việc-theo-giờ · cross-agent memory (SQLite-trước vs Postgres).
