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

## Docker E2E — verify THẬT (bổ sung sau khi cook)
- **DeepAgent tự chủ trong Docker: CHỨNG MINH THẬT**. E2E LLM thật + Docker daemon thật (không
  mock): agent TỰ gọi `docker exec` (spy bắt lệnh LLM tự gõ `whoami && cat /etc/os-release &&
  python3 -c ...`), chạy trong container Debian trixie (user=root), kết quả đúng (7×191=1337).
  Token-free (host OPENROUTER_API_KEY không lọt vào `env` container), không mount host (`.env`
  unreachable), teardown sạch (container trước=sau, không mồ côi), PII gate chặn "BÍ MẬT".
- Vòng lặp tự chủ hoàn chỉnh: giao việc → LLM tự quyết chạy shell → gõ lệnh trong container cách
  ly → đọc kết quả → tổng hợp. `test_sandbox_docker_live.py` (skipif-no-docker) khóa hành vi.
- Lưu ý: E2E gọi `run_deep_agent_work` trực tiếp (đúng hàm production); wiring qua coordinator→
  team_step_runner đã verify riêng (UAT-3 build graph qua seam).

## Firecrawl web-scrape (tích hợp cho nhân sự research, bổ sung)
- `src/tools/firecrawl_tool.py`: fetch 1 URL → markdown qua Firecrawl self-host Docker
  (localhost:3002, no-auth). Đây là năng lực `web_search_tool` cố ý KHÔNG có (snippets-only).
  READ-only, stdlib HTTP (bám convention). **SSRF guard tại nguồn**: reject localhost/private/
  link-local/metadata (agent không pivot vào nội bộ) — chặn TRƯỚC HTTP call (test verify).
- Thêm vào `read_only_toolset` như `web.scrape` → ToolCalling runtime gọi qua classify shim +
  assert_read_only. `FIRECRAWL_BASE_URL` rỗng → tool tắt (degrade). Nội dung untrusted, bounded
  8000 chars.
- **Vấp**: react loop wrap tool bằng 1 param `query` generic → LLM truyền câu hỏi thay vì URL
  cho web.scrape. Fix: `_TOOL_DESCRIPTIONS` per-tool nói rõ "query PHẢI là URL". Sau fix E2E LLM
  thật: agent tự gọi web.scrape(https://example.com) → tóm tắt "Example Domain" đúng.
- E2E thật + live test (skipif no-firecrawl): scrape example.com qua container; SSRF chặn
  localhost/metadata in-loop.

## Demo company 3-engine — UAT browser + coordinator THẬT (bổ sung)
- **Đủ 3 engine trong 1 công ty demo**: gán `agent_runtime` vào profile demo — kiem-dinh=native
  (không field), noi-dung=create_agent, nghien-cuu=deep_agent+sandbox:{provider:docker}. Bật
  `scripts/demo-mode.sh on` → giao 1 việc thật/engine qua office (preview→confirm hash-bind) →
  coordinator daemon spawn worker thật.
- **NATIVE + CREATE_AGENT chạy trọn**: kiem-dinh task=done (8 bước: 4 work + 4 review 2-tầng),
  noi-dung task=done (4 bước). Artifact + cost thật ($0.0056/$0.0018/... mỗi bước), output LLM
  thật (bảng velocity sprint, ghi chú phát hành). Có consult chéo agent trong room.
- **E2E deep qua coordinator ĐẦY ĐỦ — đóng gap "chưa chạy trọn 1 lượt"**: dispatch→coordinator
  spawn worker nghien-cuu→deep loop mở container Docker `python:3.12-slim` (verify LIVE: mount
  rỗng, env chỉ PATH/LANG/PYTHON — token-free, 0 secret)→step done→teardown sạch (0 orphan).
  Report nghiên cứu thật (market sizing + 6 xu hướng có dẫn chứng).
- **Vấp — model-compat deepagents**: `minimax/minimax-m2.7` DRIVE ĐƯỢC native+create_agent
  nhưng FAIL deep_agent loop: trả choices rỗng → LangChain `"Responses expected 1 result,
  returned 0"`. Container Docker vẫn lên đúng — lỗi ở tầng model, không phải wiring/sandbox.
  Fix: đổi nghien-cuu sang `qwen/qwen3.7-max` (tool-calling mạnh) → deep loop chạy trọn. **Bài
  học: deep_agent (create_deep_agent) đòi model tool-calling khỏe hơn 2 engine kia; chọn model
  demo phải theo engine.**

## Mở / sang sau
- **Sandbox cost cap**: hiện chỉ LLM cost (budget tháng backstop); sandbox compute cost chưa cap.
- **Deep_agent cost = None trong metered path**: cost đi qua deepagents lib (observability-only,
  đúng quyết định C4) → team_steps.cost_usd null cho bước deep. Nếu cần metering thật phải hook
  tầng khác.
- Tiếp: v21 channel binding · v19.5 kioku.
