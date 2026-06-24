# v2 M2-P5 — Graph-native Lớp B interrupt

2026-06-24 · ✅ Done (3 slice, `a82dad5`→`a01395a`, 443 test xanh, E2E thật)

> Mốc đầu của **Milestone 2**. Chuyển Lớp B approval từ gateway-queue sang **LangGraph `interrupt()` thật**: graph pause, state checkpoint-serialize, resume deterministic. AUGMENT — KHÔNG thay queue (replace ở P8/Postgres).

## Làm gì

- **Node `approval_gate`** (`src/agent/approval_gate.py`) chèn giữa compose↔deliver ở **cả 3 graph** (report/okr/resource). External → gọi `interrupt()` → graph PAUSE trước deliver, state ghi vào per-agent `SqliteSaver`; conditional edge: approve→deliver, reject→END. Internal → pass-through (edge mặc định deliver), v1 không đổi.
- **`ActionGateway.execute_approved()`** — đường "đã-người-duyệt": bỏ enqueue Lớp B lần 2 để post LIVE, nhưng Lớp A hard-deny + audit + dry-run + kill-switch + dedup VẪN áp. `deliver_report`/`create_report_page` thêm cờ `approved`; node deliver đọc `state["approval_decision"]=="approve"`.
- **Operator surface:** `worker --resume --thread <id> --decision approve|reject` (re-attach thread paused, rebuild graph từ thread_id qua `parse_thread_id`, `invoke(Command(resume=...))`). `mpm agent resume <id> <thread> --decision ...` spawn nó. Fresh external run pause → exit **3** + run-event `interrupted`. Refuse resume thread của agent khác (exit 2).
- **E2E thật** (SqliteSaver thật, profile default, channel C0BBZN04XPX): pause (exit 3, checkpoint `next=('approval_gate',)`, 0 write) → approve → **post Slack thật** (messageTs 1782314334, audit `executed` — KHÔNG re-queue) → reject (thread weekly) → KHÔNG post (write server không spawn), END sạch, audited.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| AUGMENT, không replace queue | Approve async (người duyệt sau vài giờ) cần checkpoint bền + resume xuyên process → chỉ có ở P8/Postgres. Queue path là lưới cho worker one-shot không giữ được live graph | 2 đường Lớp B cùng tồn tại tới P8 |
| Node `approval_gate` riêng (PURE) giữa compose↔deliver | `interrupt()` re-run node body khi resume → node phải không side-effect; mọi write ở `deliver` (chạy 1 lần sau approve) | Thêm 1 node + conditional edge mỗi graph |
| `execute_approved()` (id-less, chỉ `_execute(approved=True)`) | Interrupt checkpoint LÀ bằng chứng duyệt; không cần store-id như `approve(id)`. Cùng `_execute` chain → Lớp A coverage không lệch giữa 2 đường | Public bypass mới của enqueue (đã chứng minh không vượt Lớp A) |
| thread_id `<id>:<kind>:<audience>` parse khi resume | Encode đủ để rebuild ĐÚNG graph structure mà checkpoint tạo ra; round-trip lossless cho cả 4 kind | — |

## Vấp & học được

- **C1 (review bắt, test offline che mất):** approve-via-interrupt ban đầu gọi `gateway.execute()` (public, `approved=False`) → thấy external channel → **re-queue pending_approval lần 2** thay vì post; báo `delivered=True` mà Slack im. Unit test stub nguyên `deliver` dep nên không lộ. Fix: `execute_approved` + cờ `approved` xuyên 2 writer. → **luôn có 1 test chạm gateway thật (dry-run), đừng stub hết deliver.**
- **Đổi `ReportDeps.deliver` arity** (thêm `approved`) làm vỡ ~6 fake/monkeypatch ở test (lambda 2-arg, fake_page/fake_deliver thiếu kwarg). Mỗi graph có shape dep riêng (`(risks,body)` / `(rollup,body)` / `(resource,cost,body)`) → sửa từng cái. → đổi contract dep = rà hết call site fake.
- **Input-seeding KHÔNG bypass được:** review thử pre-seed `approval_decision="approve"` vào invoke đầu → graph VẪN pause (node gọi `interrupt()` vô điều kiện trước khi route). Quyết định chỉ đến từ `Command(resume=...)` thật.
- **Confluence trùng title cùng ngày** (400) ở E2E approve = giới hạn cũ P3/P4, không phải bug P5; Slack post (cái chứng minh resume→live) thành công.

## Mở / sang sau

- **E2E real-checkpointer đã chạy** (gap review để lại đã đóng): pause→approve→post thật + reject→clean, cả 2 nhánh.
- Low (chấp nhận): run-event `load_error` trên resume gắn `kind=daily` mặc định (cosmetic, vì kind thật suy từ thread trong `run_resume`); resume vẫn đòi `OPENROUTER_API_KEY` dù approve chỉ post lại text đã compose.
- **Sang P6:** FastAPI + streaming SSE (xem live run). Lớp B resume hiện operator-triggered; service-driven auto-resume (UI duyệt → service spawn resume) là P7.
