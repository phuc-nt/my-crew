# Chiến lược: MPM → harness office tổng quát (community, bám ecosystem đúng tầng)

**Ngày:** 2026-07-11 · **Loại:** tài liệu quyết định kiến trúc.
**Câu hỏi:** MPM build tiếp có thể thành harness tổng quát cho office-work (admin/hr/marketer/cc/researcher) không? Lõi tự dựng có nhanh lỗi thời so với bám hệ sinh thái LangGraph không?
**Định hướng đã chốt:** mục tiêu = **khung mã nguồn mở/community** · customer-care để SAU (ưu tiên nghề read-analyze-act) · giữ tinh thần vừa-làm-vừa-học.
**Nguồn:** code MPM thật + research Deep Agents/LangChain middleware/agentskills.io/MCP + LangGraph pitfall 2026 (các report `260711-*` cùng thư mục).

**Khuyến nghị trung tâm (1 dòng):** nâng cấp **tầng agent-loop** của MPM bằng **`AgentRuntime` Protocol đa-runtime** (cắm create_agent/Deep-Agents phía sau) — giữ nguyên guardrail+team — để MPM future-proof VÀ mở đường thành **harness office tổng quát cho community**.

---

## 0. Bối cảnh & định hướng chuyển dịch

### 0.1 MPM hôm nay
Autonomous "đội AI" cho công ty-1-người: CEO giao việc (web/Telegram) → agent tự làm PM/nội dung/nghiên cứu, đọc data thật (Jira·GitHub·Confluence·Slack), tự hành động (báo cáo/tạo trang/cảnh báo) — an toàn nhờ **Action Gateway** (mọi mutation qua 1 cửa default-deny + hard-deny + approval). ~27K LOC, ~1,573 test, domain-pack {pm,hr,admin,office}. **Đã chín ở tầng an toàn + team; agent-loop hiện TỰ VIẾT** (`_llm().complete()`, KISS, cố ý "not a tool-calling loop").

### 0.2 Vì sao chuyển hướng (2 động lực)
1. **Nỗi lo lỗi-thời (defensive):** lõi tự dựng — nhất là **agent-loop** — sợ lạc hậu so với hệ sinh thái LangGraph/LangChain đang tiến rất nhanh (Deep Agents, middleware co-evolve với model).
2. **Cơ hội mở rộng (offensive):** hình dạng "đọc-phân-tích-hành-động" của MPM KHÔNG riêng PM — đúng cho **cả cụm nghề office** (admin, hr, marketer, researcher, finance-ops…). Cùng khung, khác pack.

### 0.3 Định hướng MỚI (chốt lần này)
**Từ "PM worker" → "harness office tổng quát, mã nguồn mở/community".**
- **Tổng quát:** mỗi nghề = 1 domain-pack (đọc-phân-tích-hành-động). hr-pack đã chứng minh abstraction đúng.
- **Community:** người khác tự build office-agent trên khung này → phải dùng **chuẩn cộng đồng đã biết** (LangChain/LangGraph, agentskills.io skill, MCP tool).
- **Ngoại lệ:** customer-care (real-time + external-facing memory) khác chất → **để SAU**, giải như case runtime riêng.
- **Bất biến giữ:** guardrail (Action Gateway) + team model + 5 invariant = moat, KHÔNG đánh đổi lấy tiện lợi ecosystem.

Câu hỏi kiến trúc trung tâm của định hướng này: **làm sao bám ecosystem để không lỗi thời + community đóng góp được, mà KHÔNG mất lớp an toàn?** → §1-§5 trả lời; lõi câu trả lời là §2 (`AgentRuntime`).

---

## TL;DR (tóm tắt khuyến nghị)

**Khả thi: CÓ.** MPM đã có ~80% cấu trúc để tổng quát hoá (domain-pack + `build_graph_for` + `ToolProvider` Protocol). Thêm nghề = thêm pack.

**Nỗi lo "lõi tự dựng lỗi thời" — ĐÚNG MỘT NỬA, và nửa đúng đó có cách giải sạch:**
- **Tầng agent-loop** (tool-calling, context-mgmt, summarize, prompt-cache): **NHANH lỗi thời** → nỗi lo đúng → **bám ecosystem** (cắm `create_agent`/Deep-Agents làm employee-runtime).
- **Tầng guardrail + team + domain-pack**: **CHẬM lỗi thời** (nguyên lý tổ chức/an toàn, không phải LLM-tech) → ecosystem KHÔNG có → **tự giữ, đó là moat**.

**→ Giải pháp KHÔNG phải "bỏ lõi bám ecosystem" mà là "bám ecosystem ĐÚNG tầng nhanh-lỗi-thời, tự giữ tầng chậm-lỗi-thời", ngăn cách bằng 1 interface sạch (`AgentRuntime`).** Điều này biến MPM thành harness office community-friendly (dùng chuẩn LangChain/agentskills.io/MCP mà community đã biết) mà không mất kiểm soát an toàn.

**Rủi ro cần tránh:** dùng `create_deep_agent` TRỌN GÓI làm khung → thừa kế triết lý "trust-LLM + sandbox-security" (mất guardrail nghiệp vụ) + khoá vào Deep-Agents Beta (version churn còn tệ hơn lõi tự dựng).

---

## 1. Phân tầng theo TỐC ĐỘ LỖI THỜI (cốt lõi trả lời nỗi lo)

Không phải mọi "code tự dựng" lỗi thời cùng tốc độ. Tách ra:

| Tầng | Tốc độ lỗi thời | Ecosystem có? | Chiến lược |
|---|---|---|---|
| **Agent loop** (tool-calling, context-mgmt, summarize, prompt-cache, retry/fallback) | ⚡ NHANH — co-evolve với model, LangChain đổi liên tục | ✅ create_agent + middleware / Deep Agents | **BÁM** — cắm vào, để upstream lo |
| **Điều phối/team** (coordinator ticker, PIC, peer-review, lease) | 🐢 CHẬM — mô hình tổ chức việc, độc lập LLM | ❌ (Deep-Agents subagent chỉ ephemeral-fork) | **TỰ GIỮ** |
| **An toàn** (Action Gateway: default-deny, hard-deny, approval, audit) | 🐢 CHẬM — nguyên lý an toàn, không đổi theo model | ❌ | **TỰ GIỮ — moat** |
| **Domain-pack** (perceive/analyze/act theo nghề, tool, skill, allowlist) | 🐢 CHẬM — kiến trúc phân tách | ⚠️ một phần (skill markdown + MCP portable) | **TỰ GIỮ khung + MƯỢN nội dung community** |

**Bằng chứng "guardrail bền":** LangGraph pitfall 2026 (60% sự cố = state-mgmt; runaway $200/20ph) — những thứ này ecosystem VẪN đang vấp; MPM invariant đã miễn nhiễm. Nguyên lý an toàn không lỗi thời theo model.

**Kết luận nỗi lo:** "bám ecosystem dễ nâng cấp hơn" **đúng cho agent-loop, sai cho guardrail+team**. Ecosystem cũng lỗi thời/đổi API — chỉ khác là người khác gánh, đổi lại mất kiểm soát ở tầng cần kiểm soát nhất. Chọn bám ĐÚNG tầng.

---

## 2. ⭐ Interface then chốt: `AgentRuntime` — ranh giới bám-ecosystem

Đây là refactor quan trọng nhất để "future-proof". Tin tốt: **MPM đã có ~80% ranh giới này.**

**Hiện tại (`worker.py:56`):**
```python
def build_graph_for(loaded, settings, kind, audience):
    pack = discover_pack(loaded.domain)
    builder = pack.report_kinds.get(kind)   # ← dispatch qua pack
    return builder(...)                     # ← trả 1 compiled LangGraph
```
`ToolProvider` Protocol (`packs/tool_provider.py:24`) đã là mẫu interface pack-contributed.

**Đề xuất — nâng thành `AgentRuntime` Protocol:**
```python
@runtime_checkable
class AgentRuntime(Protocol):
    # 1 employee = 1 runtime nhận việc, trả (kết quả + đề xuất action)
    def build(self, loaded, settings, task, audience) -> CompiledGraph: ...
```
Rồi có nhiều implement, **cắm được ecosystem phía sau mà coordinator/gateway KHÔNG cần biết:**
- `NativeGraphRuntime` — graph tự viết hiện tại (`perceive→analyze→compose→deliver`). Giữ cho nghề read-analyze-act đơn giản + cần kiểm soát chặt.
- `CreateAgentRuntime` — bọc LangChain `create_agent` + middleware (summarize/call-limit/fallback). Cho nghề cần tool-calling loop linh hoạt.
- `DeepAgentRuntime` — bọc `create_deep_agent` (fs + subagent + skills). Cho researcher đọc-nhiều/tổng-hợp.

**Bất biến giữ nguyên với MỌI runtime:** output đi qua **deliver → Action Gateway**; runtime chỉ được cấp tool READ + "produce internal artifact", KHÔNG tool mutation trực tiếp. → dù loop là gì, an toàn vẫn ở gateway.

**→ Đây là "bám ecosystem mà không bị khoá":** runtime là `create_agent` hôm nay, Deep Agents mai, model-native agent năm sau — thay được sau interface, gateway + team không đổi.

---

## 3. Tổng quát hoá cho các nghề office

### 3.1 Nghề "read-analyze-act" (khớp MPM sẵn) — ưu tiên
admin · hr · marketer(report) · researcher · finance-ops… đều chung hình dạng **đọc data → phân tích → soạn → (duyệt) → hành động**. Khớp `perceive→analyze→compose→deliver`.
- Mỗi nghề = 1 **domain-pack**: graphs(kind) + ToolProvider(read) + write_handlers+allowlist + prompts + skills.
- hr-pack đã CHỨNG MINH abstraction đúng (gate `git diff src/=∅`, thêm Google-Sheets adapter mà lõi chưa biết GSheet).
- Thêm marketer/researcher = lặp lại pattern hr-pack. **Khả thi cao, rủi ro thấp.**

### 3.2 Ngoại lệ: customer-care (để SAU, ghi nhận vì sao khó)
CC = hội thoại real-time nhiều lượt với **người NGOÀI** → phá 2 thứ của MPM:
- **Batch/scheduled model** (MPM chạy theo tick/report) ≠ real-time conversation loop.
- **external=zero-memory red-line** — CC cần nhớ ngữ cảnh khách qua nhiều lượt = external-facing memory. Đây là mâu thuẫn trực diện với invariant load-bearing nhất.
→ CC cần **runtime + memory model riêng** (conversation-scoped, external-memory có kiểm soát PII/injection). **Không nhét vào harness read-analyze-act.** Giải sau như case riêng (có thể chính là chỗ `CreateAgentRuntime` + memory-scope external riêng biệt tỏa sáng).

---

## 4. Community: dễ tích hợp tool/skill/script cộng đồng không?

**Tách theo loại asset (đã kiểm code Hermes/OpenClaw):**

| Asset | Portable? | Vì sao | Cách |
|---|---|---|---|
| **Skills (SKILL.md markdown)** | ✅ DỄ | chuẩn **agentskills.io** (frontmatter name/description/version/platforms + body) — là prompt, không phải code. Hermes/OpenClaw/Deep-Agents cùng chuẩn | MPM chuẩn hoá skill-loader theo agentskills.io → copy skill community vào chạy |
| **MCP servers** | ✅ DỄ | cầu nối chung — Hermes/OpenClaw/MPM(langchain-mcp-adapters)/Deep-Agents đều MCP client | thêm MCP server config → có tool ngay |
| **Scripts (bash watcher/no_agent)** | ✅ DỄ | là shell, copy chạy | pack script + coordinator gọi |
| **Tools (Python/TS khoá registry riêng)** | ❌ REWRITE | Hermes `registry.register()` / OpenClaw TS-plugin gắn cứng runtime của họ | không tái dùng as-is (rebuild cũng không cứu) |

**Kết luận community:** thứ tái dùng được = **skill-markdown + MCP + script**. Muốn "dễ mượn community" thì việc cần làm là **(a) chuẩn hoá skill-loader theo agentskills.io + (b) MCP host mạnh** — CẢ HAI độc lập với việc bám-ecosystem-loop. Tool Python khoá-registry thì hệ nào cũng phải rewrite.

**→ Cho mục tiêu community-framework:** giá trị lớn nhất KHÔNG phải "dùng create_agent" mà là **chuẩn hoá 3 điểm mở**: (1) skill = agentskills.io, (2) tool = MCP, (3) domain = pack. Đây là 3 "ổ cắm" để community đóng góp. Bám ecosystem-loop là phụ trợ (giúp dev quen LangChain đóng góp runtime mới).

---

## 5. Kiến trúc harness office community-friendly (tổng hợp)

```
┌─ TẦNG LOOP (bám ecosystem — thay được) ─────────────────────┐
│ AgentRuntime Protocol:                                       │
│   NativeGraphRuntime | CreateAgentRuntime | DeepAgentRuntime │
│   → summarize / prompt-cache / tool-calling: từ LangChain    │
└──────────────────────────┬──────────────────────────────────┘
                           │ (mỗi employee = 1 compiled graph)
┌─ TẦNG ĐIỀU PHỐI (tự giữ — bền) ─────────────────────────────┐
│ StateGraph coordinator (ticker+lease) + team (PIC/review)    │
└──────────────────────────┬──────────────────────────────────┘
                           │ (mọi mutation)
┌─ TẦNG AN TOÀN (tự giữ — moat) ──────────────────────────────┐
│ Action Gateway: default-deny + hard-deny + approval + audit  │
└──────────────────────────┬──────────────────────────────────┘
                           │ (cắm vào)
┌─ TẦNG DOMAIN (pack: khung tự giữ + nội dung community) ──────┐
│ {admin,hr,marketer,researcher}-pack                          │
│   = graphs(kind) + MCP-tools + agentskills.io-skills + allow │
└──────────────────────────────────────────────────────────────┘
```

**3 ổ cắm community:** skill(agentskills.io) · tool(MCP) · pack(domain). **1 ổ cắm ecosystem:** runtime(AgentRuntime). **2 tầng bất biến:** gateway + team.

---

## 6. Đánh giá cuối cho từng lo ngại của anh

| Lo ngại | Trả lời |
|---|---|
| "Lõi tự dựng nhanh lỗi thời" | Đúng cho **agent-loop** → bám ecosystem qua `AgentRuntime`. Sai cho gateway+team → tự giữ, bền. |
| "Bám ecosystem dễ nâng cấp hơn" | Đúng cho loop. Nhưng bám TRỌN GÓI (`create_deep_agent` làm khung) = mất guardrail + khoá Beta version. Bám qua interface = được lợi, giữ kiểm soát. |
| "Thành harness office tổng quát" | Khả thi — domain-pack đã chứng minh (hr-pack). Thêm nghề read-analyze-act = thêm pack. CC để sau (khác chất). |
| "Dễ mượn tool/skill community" | Skill(markdown)+MCP+script: dễ, và **độc lập với bám-ecosystem-loop**. Chuẩn hoá agentskills.io + MCP là việc cần làm. Tool Python khoá-registry: hệ nào cũng rewrite. |

**Chốt định hướng:** MPM **không cần rebuild**, cần **3 việc kiến trúc để vừa future-proof vừa community-friendly**:
1. **`AgentRuntime` interface** — tách loop khỏi điều-phối, cắm ecosystem (Native/CreateAgent/DeepAgent runtime). Chống lỗi-thời tầng loop.
2. **Chuẩn hoá 3 ổ cắm community** — skill=agentskills.io, tool=MCP, domain=pack. Để community đóng góp.
3. **Giữ nguyên gateway+team+invariant** — moat, đừng đụng.

Đây là "vừa-làm-vừa-học" đúng nghĩa: học rằng **ranh giới** (interface) mới là thứ quyết định future-proof, không phải "viết lại bằng framework mới".

---

## 7. Câu hỏi chưa giải quyết
1. **`AgentRuntime` refactor effort:** `build_graph_for` hiện dispatch qua `pack.report_kinds` — nâng thành Protocol đa-runtime tốn bao nhiêu? Cần đọc kỹ `worker.py` + pack graphs để ước lượng (nghi ~1-2 tuần, không phải rebuild).
2. **Skill-loader hiện có chuẩn agentskills.io chưa**, hay cần vá frontmatter/discovery để mượn skill Hermes/community? Cần so `src/skills/skill_loader.py` với chuẩn.
3. **Community governance:** pack/skill do người ngoài đóng góp → cần review-gate (allowlist an toàn, skill không injection). Ai duyệt? (giống lo ngại shared-memory injection của Deep Agents.)
4. **CreateAgentRuntime cấp tool thế nào để KHÔNG cho LLM tự gọi tool-ghi?** create_agent bản chất là tool-calling loop — phải giới hạn toolset = read-only + internal-artifact, mutation vẫn qua gateway ở deliver. Cần thiết kế cụ thể (đây là điểm khó nhất khi bám ecosystem-loop mà giữ invariant).
5. **Customer-care runtime + external-memory:** khi nào giải, mô hình nào (conversation-scoped memory + PII-firewall)? Ngoài phạm vi lần này nhưng ảnh hưởng thiết kế `AgentRuntime` (phải đủ rộng để sau này thêm conversation-runtime).
