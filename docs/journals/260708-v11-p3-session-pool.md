# v11 P3 — MCP session-reuse pool + version contract (2026-07-08)

my-pm (trong scope). Đảo quyết định cũ "teardown per call" — chủ dự án đã duyệt. THE INVARIANT nguyên vẹn (pool là tầng transport, không đụng verdict flow gateway).

## Đã làm

- **`McpSessionPool` (owner-task design)** — `src/adapters/mcp_session_pool.py`: spawn 1 subprocess/server/RUN thay vì /call. Vì anyio cancel-scope của stdio client bó theo TASK (mở/đóng khác task = RuntimeError) và graph node là SYNC: pool sở hữu 1 thread + event-loop riêng; mỗi server 1 coroutine chủ (owner) tự `async with client.session(auto_initialize=False)` bên trong nó, đọc `serverInfo.version` từ `initialize()`, phục vụ call qua `asyncio.Queue`; sync caller submit qua `run_coroutine_threadsafe` + block trên `concurrent.futures.Future`. Mở/gọi/đóng đều trong owner task.
- **Adapter pool-aware**: `call_tool` đọc contextvar `current_pool()` — có pool → submit owner-task; None → per-call cũ (backward-compat, rollback = bỏ wiring). Timeout tách spawn (20s) vs call (60s).
- **Wiring run-scope**: `worker.py` (report/inbox/tasks branch), `run_manager._run_sync` (contextvar set trên chính thread to_thread chạy graph.stream), `mpm_automate_cmd`. Ops-alerts KHÔNG wrap (không call_tool).
- **Version contract**: `MIN_SERVER_VERSIONS {jira 4.2.0, confluence 1.5.0, slack 1.3.0}`, `check_min_version` warn-once/server (packaging.Version compare), server lạ (Linear/extra) bỏ qua (F10). Enforce sau `MCP_MIN_VERSION_ENFORCE=true`; default warn-only (P4 mới flip).
- **integration_health whoami**: slack check nâng từ presence-bool → live `whoami` probe (bounded 10s); `TOKEN_EXPIRED` → hint "lấy lại từ browser"; server cũ (no whoami) → fallback presence. Docstring cập nhật trung thực (giờ có gửi token đi verify).
- **inbox retry-on-not-found**: channel không thấy trong list (cache 15') → retry 1 lần `bypass_cache:true` trước khi raise (F7).

## Verified

- **Live pool 7/7** (server thật): 3 call cùng server → **1 spawn**, version read 1.3.0, close → 0 orphan, fallback OK.
- **Leak test 2/2**: parent bị **SIGTERM VÀ SIGKILL** giữa session mở → **0 orphan node** (during=2→after=0). SIGKILL bỏ qua mọi cleanup Python → con chết nhờ stdin-EOF handler P1/P2. Đây là điều kiện an toàn của cả quyết định reuse.
- **Benchmark**: workload weekly-shaped (4 jira search + 1 slack) **5 spawn → 2 spawn**, wall **3.23s → 1.85s (−43%)**. Epic nhiều hơn → giảm càng lớn (mỗi search thêm 0 spawn thay vì 1).
- **1232 test** (1206 cũ + 26 mới hermetic: 17 pool + 7 whoami + 2 inbox), ruff sạch.
- Code-review DONE_WITH_CONCERNS → vá hết 3 MAJOR + 1 MED:
  - **M1**: cancel giữa `ainvoke` → `CancelledError` là BaseException, `except Exception` không bắt → future in-flight không resolve → caller kẹt 60s. Vá: track `in_flight`, fail nó trong CancelledError handler. + test mới chứng minh fail-fast.
  - **M2/M3**: `_ensure_server` publish state trước khi owner tồn tại + `started.wait()` không check return → caller race half-built state. Vá: publish sau `_start`, gate reader trên `owner is not None`, raise nếu wait timeout.
  - **MED2**: health `with ThreadPoolExecutor` block ở exit đến 60s dù bound 10s (`shutdown(wait=True)`). Vá: `shutdown(wait=False)` trong finally.

## Bài học

- **anyio task-affinity = ràng buộc kiến trúc cứng**: không thể mở session ở loop này đóng ở loop khác. Owner-task (1 coroutine giữ trọn vòng đời session) là design đúng duy nhất cho sync-caller. Red-team chốt design này trước khi cook.
- **CancelledError ≠ Exception (3.12)**: `except Exception` bỏ sót cancel → future không resolve → caller kẹt. Mọi handler dọn dẹp phải bắt CancelledError riêng.
- **`with ThreadPoolExecutor` block ở __exit__**: `shutdown(wait=True)` đợi task xong — timeout ở `.result()` không cứu. Bound thật cần `wait=False`.
- **stdin-EOF handler (P1/P2) là lưới an toàn của reuse (P3)**: nhờ nó, SIGKILL parent không để lại orphan. 3 phase khớp nhau thành 1 bộ.

## Unresolved / next

- M2/M3 hiện latent (mỗi caller sở hữu 1 pool đơn-thread); nếu sau này share pool đa-thread thì fix đã sẵn.
- P4: esbuild bundle 3 server + publish npm (bản đã sync serverInfo) + installer npm-path + flip min-version enforce mặc định.
