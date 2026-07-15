# v47 — Docker-UX: daemon dễ thấy, image warm sẵn, lỗi rõ ràng
2026-07-15 · ✅ Done

## Làm gì
- **Health check Docker chủ động** (`integration_health._docker_check`): probe `docker info` giới hạn 5s, degrade ✗ sạch (FileNotFoundError/TimeoutExpired/returncode≠0) — panel Sức khỏe báo daemon tắt TRƯỚC khi giao việc, thay vì chờ `SandboxDenied` lúc chạy.
- **Warm image opt-in** (`prepull_sandbox_image` + `mpm sandbox prepull [image]`): present-check no-op → else pull, trả dict `{ok,pulled,image,message}`, KHÔNG BAO GIỜ raise (daemon tắt/offline → message rõ). Để bước deep_agent ĐẦU không phải chờ pull.
- **DRY**: hằng số `SANDBOX_DEFAULT_IMAGE` thay 2 literal `python:3.12-slim` — health/prepull/backend cùng tham chiếu một chuỗi.
- **Docs** (deployment-guide §6a/§8/§9): note "shell thật CHỈ trong container = yêu cầu bảo mật", colima nhẹ hơn Docker Desktop, lệnh warm, 2 dòng sự cố — string khớp code (cross-check hint + SandboxDenied + tên CLI).

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Chọn (d) Docker-UX, BÁC exec-tier Seatbelt | Seatbelt = cách-ly-bằng-policy yếu hơn container; thêm backend thứ 3 phá YAGNI | Vẫn cần daemon cho deep_agent — nhưng đó là moat, không phải lỗi |
| Health check LUÔN chạy, nhãn "chỉ cần deep_agent" | integration_health không có fleet-view; ✗ không hù đội no-shell | 1 dòng ✗ với đội Docker-free (đã dán nhãn giảm nhẹ) |
| prepull trả dict, không raise | CLI/health surface in được; daemon tắt là no-op sạch, không crash caller | Nuốt cả lỗi non-"not found" ở `images.get` → fall-through pull (chấp nhận: best-effort, không phải biên bảo mật) |
| prepull opt-in, KHÔNG auto lúc startup | đội Docker-free không bị ép pull | Vận hành phải nhớ chạy 1 lần (đã ghi docs) |

## Vấp & học được
- Test prepull đặt file RIÊNG (`test_sandbox_prepull.py`) chứ không nhét `test_sandbox_backend.py` — file kia có `pytestmark=skipif(deepagents absent)`, mà prepull độc lập deepagents; nhét vào sẽ bị skip oan trên host không cài dep.
- 7 lỗi ruff tồn dư ở file KHÔNG liên quan (coordinator_graph, team_task_prompt, clarify_service, team_step_runner, routes_connections) — xác nhận ngoài scope, 4 file v47 sạch. Không sửa lan man.

## Mở / sang sau
- Còn #5 MCP-overhead (office cross-synth 92s vs Hermes 56s — spawn MCP mỗi call): cân nhắc session-pool MCP mặc định cho office. Là mục cuối chuỗi "3,2,5 tuần tự".
