# v48 — team-step MCP pool reuse (office cross-synth bớt spawn)
2026-07-15 · ✅ Done

## Làm gì
- Bọc lời gọi `run_team_step(...)` trong worker (`_run_team_step_kind`) bằng helper CÓ SẴN `_run_with_mcp_pool` — mọi `call_tool` trong một team-step giờ dùng lại 1 subprocess MCP / server thay vì spawn `node` mới mỗi call.
- Là đòn cuối chuỗi "3,2,5 tuần tự": #5 MCP-overhead. Benchmark đo office cross-synth 92s vs Hermes 56s — nguyên nhân là spawn-per-call.
- Test seam ổn định: stub `run_team_step` bắt `current_pool()` lúc chạy → khẳng định non-None (pool active cả bước, gồm cả review in-step).

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Bọc ở worker.py:452 (1 site) | 3 nhánh anh em (report/inbox/tasks) đã bọc y hệt; team-step là nhánh DUY NHẤT quên | 0 — thuần thêm, không đổi contract |
| Bọc TRONG try có sẵn | teardown pool lỗi vẫn được except cũ ghi `_write_outcome("failed")` | không |
| 1 wrap phủ cả review | `_run_review` chạy BÊN TRONG `run_team_step` → không cần wrap thứ 2, không lồng pool | không |
| Assert ở seam `current_pool()`, không nội bộ pool | bền trước refactor; không cần spawn node thật trong test | test không đo latency thật (đo là việc của benchmark) |

## Vấp & học được
- `_run_team_step_kind` import `run_team_step` cục bộ (trong hàm) → monkeypatch attribute trên module `team_step_runner` mới ăn; nếu import ở top-module thì patch site khác. Xác nhận cơ chế bằng chạy test standalone.
- Pool (v11 P3) yêu cầu owner-task/anyio trên CÙNG thread gọi `call_tool`; team-step chạy sync trên main thread của worker — hệt 3 nhánh kia, nên không cần `asyncio.to_thread`.

## Mở / sang sau
- Đo lại office cross-synth sau v48 để xác nhận thu hẹp khoảng 92s→? (việc của bên benchmark).
- `team-tick` có gọi MCP không (spawn-per-call)? Chưa truy — nếu có, cùng cách bọc.
