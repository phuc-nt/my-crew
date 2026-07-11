# v20.5 — Runtime-tiers: team-step egress + guardrail phân tầng + DeepAgent sandbox
2026-07-11 · HOÀN TẤT (1797 BE + 178 FE xanh, ruff/tsc sạch, DeepAgent E2E LLM thật + fake sandbox)

## Làm gì
- **Phase 0 — team-step egress qua gateway** (`team_step_egress.py`): điều tra red-team phát hiện
  `external_write` hook (thiết kế v12) CHƯA nối → team-step không egress được. Nối hook →
  per-agent ActionGateway (Lớp A/B + audit), opt-in `team_step_egress: {channel}`. Nền cho mọi
  runtime egress.
- **Guardrail phân tầng** (`config.py`): `caps()` → `runtime_loop_limit` per-runtime (native 0 <
  create_agent 8 < deep 16); `cost_cap_usd` observability-only; config tới runtime qua build_task.
- **DeepAgentRuntime cháy thật** (`deep_agent_runtime.py`+`deep_agent_loop.py`): create_deep_agent
  chạy shell CHỈ trong sandbox. Fail-closed up-front (allowlist `{fake,docker}`). E2E LLM thật:
  shell tính 42, PII gate chặn memory.
- **Sandbox backend** (`sandbox_backend.py`): fake (test) + docker (self-hosted, token-free env,
  không mount host .env/SSH). PII gate + teardown reaper.
- **Wizard chọn runtime** (`IdentityStep.tsx`): picker + role prefill (`recommended_runtime`).

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Điều tra gateway-gap TRƯỚC cook | Red-team nói deliver→gateway không tồn tại → phải biết thật/giả | Hoãn cook 1 nhịp; hóa ra là tính năng chưa làm, không phải bug |
| Provider = Docker self-hosted (KHÔNG Modal/E2B) | User: không muốn dịch vụ ngoài + phí + gửi data bên thứ 3 | Nặng hơn (macOS cần Docker Desktop); real E2E follow-up |
| cost_cap = observability-only | Cost cap thật là company task-level ($2); per-runtime không có seam enforce (red-team C4) | Không giả enforce; document trung thực |
| PII gate: deep chạy context external-safe | deep có shell+egress → internal data trong prompt = exfil target (H2) | Deep mất grounding nội bộ (dùng tool-calling nếu cần) |
| Fail-closed = positive allowlist | backend=None→StateBackend, `local`→host shell đọc .env (red-team C3) | Chỉ fake/docker; reject phần còn lại |
| Wizard fold vào IdentityStep | Tránh step-renumber phá Review (red-team F7) | Không có step riêng cho runtime |

## Vấp & học được
- **Red-team đọc deepagents wheel thật cứu khỏi ship lỗ hổng**: 6 Critical grep-verified — nền
  plan gốc (deliver→gateway, execute có env, backend=None refuse, cost cap) đều SAI vs API thật.
  Nếu cook thẳng theo plan gốc = ship shell-đọc-.env. Đọc source dependency thật > tin doc.
- **deepagents deprecation warning xác nhận red-team C3 nguyên văn**: LocalShellBackend "provides
  no sandboxing (execute runs on the host)" — đúng lý do reject `local`.
- **`external_write=None` là tính năng chưa làm, không phải bug**: team-step vốn không egress
  (egress đi qua report graph). v20 KHÔNG có lỗ hổng — chỉ docs over-claim (đã đính chính).
- **DeepAgent E2E thật là bằng chứng**: LLM chạy shell trong fake sandbox → 42 đúng, PII gate
  chặn "BÍ MẬT". Chứng minh toàn bộ luồng an toàn bằng thực thi, không chỉ assert.

## Mở / sang sau
- **Real Docker E2E**: fake chứng minh WIRING; isolation OS thật cần Docker daemon chạy +
  token-scan container thật (follow-up khi bật Docker).
- **Sandbox cost cap**: hiện chỉ LLM cost (budget tháng backstop); sandbox compute cost chưa cap.
- Tiếp: v21 channel binding · v19.5 kioku.
