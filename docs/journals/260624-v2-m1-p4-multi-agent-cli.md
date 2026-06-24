# v2 M1-P4 — Multi-agent CLI (`mpm agent ...`) · 🏁 ĐÓNG MILESTONE 1

2026-06-24 · ✅ Done (3 slice 1→2→3, commit 94604b7 / ed2ed02 / 8be3e71)

## Làm gì

- **Surface CLI quản lý N agent** — `python -m src.entrypoints.mpm agent ...`. Additive: cli.py/cron.py giữ làm legacy single-agent. Hầu như KHÔNG logic mới — chỉ parse + dispatch + per-agent store access trên primitive P3.
- **`mpm.py`** (dispatch shell) + 3 module nhóm lệnh (registry / run / manage) — tách để mỗi file <200 LOC.
- **`agent list`** — đọc registry + name + last-run (dòng cuối `runs.jsonl`, B1). **`agent register <id>`** — scaffold `profiles/<id>/` từ template default + text-append `{id, enabled: true}` vào registry.yaml (idempotent, validate id, lỗi nếu trùng, giữ comment).
- **`agent run <id> --report <kind>`** — spawn worker subprocess (CÙNG argv shape service P3, reuse `service._worker_argv/_supervise` → lock-step contract), chờ exit + đọc run-event, in kết quả. Spawn fn injectable → test assert argv không cần process thật.
- **`agent approvals/approve/reject/audit <id>`** — **GAP-CLOSER**: build gateway/audit-log ở `agent_data_dir(<id>)` (qua `load_profile(id, data_dir=agent_data_dir(id))` → settings.data_dir → store per-agent), nên Lớp B + audit cuối cùng trỏ đúng store đã migrate. cli.py (global) sau migrate thấy rỗng → cli in note trỏ sang `mpm agent`.
- 414 test xanh, ruff sạch, mọi file mới <200 LOC.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| File mới `mpm.py` (không rewrite cli.py) | additive, không breaking cli/cron v1; surface multi-agent sạch | 2 entrypoint song song (mpm + cli legacy) |
| `agent run` spawn subprocess (không in-process) | đồng nhất đường spawn với service P3; isolation process thật | phải reuse service helper |
| reuse `service._worker_argv/_supervise` | argv worker phải lock-step giữa CLI run 1 lần và scheduler → 1 contract | entrypoint→runtime import (chấp nhận, helper stable + tested) |
| approve copy `_dispatch_approved_action` (~6 dòng), KHÔNG import cli | tránh entrypoint→entrypoint coupling (mpm phụ thuộc cli legacy = sai hướng) | 2 bản copy nhỏ; nếu drift thật → extract sang src/actions/ |
| Per-agent management = `load_profile(data_dir=agent_data_dir(id))` | 1 cơ chế: settings.data_dir → mọi store per-agent. Đóng gap "cli stale" P3 | mpm + cli xem 2 store khác nhau (đúng — P4 hợp nhất) |

## Vấp & học được

- **YAML 1.1 boolean trap (lần 2):** test register dùng id `"A"`/`"B"` viết hoa → `_validate_agent_id` reject (regex `^[a-z0-9]`). Không phải bug, là validate đúng; sửa test sang id thường. (Lần 1 ở P3 là `id: on`→bool.) Bài học: id agent luôn lowercase, test phải tuân.
- **Fake settings mặc định `dry_run=True`:** test approve gọi handler nhưng gateway dry-run → handler không chạy → KeyError. Fix: `build_settings_from_dict({..., "dry_run": False})` để approve thật sự dispatch.
- **Spy lambda trả sai:** `seen.setdefault(k,v) or 0` trả `v` (list truthy) thay vì 0 → dispatch test đỏ. Fix: helper `_spy` trả 0 tường minh.
- **Review xác nhận gap-closer structurally real:** test seed store agent `a`, assert `b` rỗng → không phải vacuous. Smoke thật: `mpm agent approvals default` đọc approval #20 mà `cli audit` (global) báo rỗng sau migrate.

## Mở / sang sau

- **2 parity gap kế thừa từ cli (KHÔNG phải regression P4):** `reject <id-không-tồn-tại>` báo success/exit-0 (`ApprovalStore.set_status` UPDATE vô điều kiện); `_approve` chỉ catch `ValueError` (handler/network error escape traceback). Cả 2 giống hệt `cli._run_reject/_run_approve` → nếu muốn sửa, sửa ở gateway/store cho cả 2 caller.
- **Đề xuất khử trùng lặp:** extract `dispatch_approved_action` sang `src/actions/` để cli + mpm cùng import (bỏ coupling entrypoint↔entrypoint mà vẫn DRY). Chưa cần.
- **🏁 MILESTONE 1 XONG** (P1 config-injection → P2 profile → P3 registry+worker+service → P4 mpm CLI): N agent / N project cô lập hoàn toàn, chạy qua CLI/worker + scheduler, guardrail per-agent. **Chưa có UI, chưa Postgres** → đó là **M2** (P5 interrupt/streaming → P6 SSE → P7 web dashboard → P8 Postgres + agent-written memory).
