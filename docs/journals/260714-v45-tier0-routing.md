# v45 — tier-0 routing (no-shell step bỏ Docker qua create_agent + StateBackend)
2026-07-14 · ✅ Done (2312 BE)

User muốn deep_agent nhanh + linh hoạt hơn, bỏ Docker. Research + 5 phản biện + đo thật đảo lại bài toán: **đòn bẩy đúng KHÔNG phải bỏ Docker** (đo: cold-start ~0.4s/step, rẻ; host-exec KHÔNG an toàn cho fleet autonomous + injectable — brainstorm bác) mà là **KHÔNG spin Docker cho việc không cần shell**. deep_agent shell thực chất chỉ dùng làm scratchpad ghi report .md. → cho create_agent (tier nhanh, 0 Docker đã có) một scratch surface + router per-step.

## Làm gì
- **P1 `needs_shell` signal**: field trên TeamStepPlan/TeamStep (như needs_review), LLM-set + validated, default False. Bind vào `decomposition_content_hash` **có điều kiện** (chỉ emit key khi True) → DAG all-no-shell hash BYTE-IDENTICAL pre-v45 → task cũ KHÔNG false-stall lúc migrate. Prompt decompose: "true CHỈ khi bước phải chạy shell".
- **P2 StateBackend scratch cho create_agent**: `FilesystemMiddleware(backend=StateBackend())` bind vào langchain create_agent (verify: file trong graph-state, KHÔNG execute/host/subprocess/Docker). **Strip tool `execute`** khỏi middleware (filter `.tools` + fail-loud guard) → create_agent TUYỆT ĐỐI không shell. + compose-early clause + read-back `result["files"]` (FileData.content) vào reply.
- **P3 router per-step**: `resolve_step_runtime(loaded, step)` — needs_shell→deep_agent (raise `SandboxUnavailableForShellStep` nếu agent không sandbox = fail-closed); no-shell trên agent deep_agent-pinned→DROP create_agent (win tốc độ); còn lại giữ profile kind; None/kill-switch→native. team_step_runner gate `_extra` theo EFFECTIVE kind.
- **P4 UAT thật**: create_agent chạy task reason+write-report, ghi `/draft_analysis.md` (compose-early), read-back surface vào reply, **0 container**. Router: no-shell→ToolCalling, shell→DeepAgent. PASS.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Bỏ Docker = all-cost-no-speed, GIỮ | đo cold-start 0.4s (không phải nguyên nhân chậm); shell-on-host phá invariant (đọc .env/exfil) | Docker vẫn là dependency |
| Win = route no-shell sang create_agent | deep_agent shell chỉ scratchpad; create_agent 0-Docker đã có, chỉ thiếu file-scratch | Cần StateBackend + router |
| needs_shell hash có điều kiện (emit khi True) | all-False hash = pre-v45 → 0 false-stall task cũ (mirror carve-out system_inserted) | — |
| Mặc định create_agent, leo khi needs_shell | injection ép no-shell chỉ làm fail (tier nhẹ không shell → không RCE); ép có-shell chỉ leo lên sandbox (an toàn) | fail-closed 2 chiều |
| Chỉ drop deep_agent→create_agent (native giữ nguyên) | tránh regression: native team-step chạy 1-shot khác create_agent tool-loop | native no-shell không hưởng tier nhanh |

## Vấp & học được
- **Instinct đúng, đòn bẩy sai**: "bỏ Docker để nhanh" — đo thật cho thấy Docker 0.4s không phải nút thắt. 5 phản biện của user bắt đúng status-quo-bias (gộp "chậm" vào moat). Đo trước khi tin.
- **subprocess+tmpdir = BẪY** (research): env-scrub không giấu file .env/.ssh trên đĩa, macOS không chặn network per-process. Không có đường execute-shell-không-Docker-an-toàn trên macOS.
- **Ảnh so 3 harness (host-exec+approval)**: bổ sung insight (trục approval-gate) nhưng brainstorm bác: MPM autonomous (không ai duyệt 3h sáng) + injectable → approval cho shell là category-error (write legible, shell không). Không copy host-exec.
- **TeamStep field required phá fixtures**: thêm needs_shell dạng positional-required → 3 test TypeError. Vá: chuyển sang defaulted field (sau clarify_id). Bài học: field mới trên dataclass dùng chung phải có default.
- **`_extra` theo effective-kind, không profile-kind**: khi drop deep_agent→create_agent, mọi kwarg đi ToolCallingRuntime — pop đủ (v43/v44), không leak vào build_team_task_graph.

## Mở / sang sau
- native no-shell step chưa hưởng tier nhanh (giữ native tránh regression) — cân nhắc nếu đo thấy đáng.
- gather/review row (system_inserted) luôn no-shell (schema default) — đúng hiện tại; comment lại nếu gather làm gì hơn text.
- gVisor (Linux prod) nhanh+mạnh hơn Docker — infra decision riêng, sau đo startup prod.
- E3 cap-3-vs-5 + on-turf benchmark (team DAG+PIC thắng sân nhà?) vẫn mở từ phản biện #2/#3 — chưa làm.
