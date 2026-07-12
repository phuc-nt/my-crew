# Kho công cụ OpenClaw + Hermes — tham khảo cho my-crew (MPM)

**Ngày:** 2026-07-12 · **Mục đích:** tổng hợp tool/skill/script/CLI mà agent OpenClaw + Hermes đang dùng, phân nhóm chức năng, đánh giá cái nào my-crew **tích hợp được / build tương tự / bỏ qua**.
**Nguồn:** đọc THẬT trên máy (`~/.openclaw`, `~/workspace/hermes-agent`).

> **Đính chính 2026-07-12 (đối chiếu code thật):** bản gốc đánh giá THẤP my-crew ở 4 chỗ — skill-loader ĐÃ hỗ trợ agentskills.io (`skill_loader.py` load `<slug>/SKILL.md` từ v20); MCP đã có adapter + session-pool + spawn-gate (`pack_mcp_gate.py`); Firecrawl ĐÃ wire vào `read_only_toolset` (không chỉ "có hướng dẫn"); hr-pack KHÔNG có "GSheet adapter" mà spawn `gws` CLI read-only (`hr-pack/tools.py`). Chi tiết + roadmap: `plans/reports/assessment-260712-1818-openclaw-hermes-tools-integration-readiness-report.md`. **Quyết định CEO:** làm HẠ TẦNG CHUNG trước (wake-gate / cronjob-tool / kanban-tool / clarify), nghề-specific sau.

## Nguyên tắc đọc bảng (my-crew khác bản chất 2 hệ kia)

my-crew = **worker có guardrail** (Action Gateway default-deny, mọi write ra ngoài qua 1 cửa). OpenClaw/Hermes = companion/framework "trust LLM, chặn ở tool". Nên khi tham khảo:
- **3 kiểu portable:** skill (markdown agentskills.io) = copy được · tool (MCP server) = cắm được · script (bash) = chạy được. **Tool Python khoá-registry của Hermes/OpenClaw = KHÔNG copy, phải build lại.**
- **Mọi tool WRITE** khi build cho my-crew phải qua Action Gateway. Tool READ đi qua pack ToolProvider.
- **Convention my-crew:** HTTP = stdlib `urllib` (không thêm httpx/requests); credential env-only; không cho LLM tự gọi tool-ghi.

---

## 1. Đang chạy thật trên máy này

**OpenClaw — 8 plugin enabled:** `telegram · brave · memory-core · openrouter · anthropic · ollama · zai · firecrawl`
**OpenClaw skill (personal 20 / research 10):** gws-* (Gmail/Calendar/Drive/Sheets/Docs/Tasks — Google Workspace), goodreads-read/write, academic-research, reddit-readonly, youtube-ultimate, facebook-group, typefully, voz.
**OpenClaw common-scripts:** facebook, goodreads, google, google-drive, reddit, research, youtube, session-mgmt.
**Hermes — 76 tool module + skills 24 category + 17 plugin** (browser, memory 8-provider, model 30-provider, kanban, observability…).

---

## 2. Phân nhóm chức năng + đánh giá cho my-crew

### A. Đọc dữ liệu công việc (READ) — ưu tiên cao, hợp nghề office

| Công cụ (nguồn) | Làm gì | my-crew |
|---|---|---|
| **Google Workspace** (OpenClaw gws-* skill + `gws` CLI) | Gmail/Calendar/Drive/Sheets/Docs/Tasks | **Tích hợp** — nghề admin/HR cần. hr-pack ĐÃ spawn `gws` CLI đọc Sheets (`hr-pack/tools.py`, transport như PM spawn `gh`). Mở write (gmail-send/docs-write) = thêm write_handler qua Gateway trên transport sẵn. |
| **Firecrawl** (OpenClaw plugin, đã dựng local) | Scrape/crawl web → markdown, kể cả JS-heavy | **ĐÃ WIRE** — `firecrawl_tool.py` SSRF-guarded, vào `read_only_toolset` (`web.scrape`) từ v20.5. Nghề researcher/marketer dùng được ngay. |
| **web search** (brave/exa/tavily/perplexity — cả 2 hệ) | Tìm web snippet | **Đã có** `web_search_tool.py` (tavily/brave, snippets-only). Giữ. |
| **session_search** (Hermes, FTS5 + LLM summarize) | "3 tuần trước quyết định gì?" — tìm transcript cũ rồi tóm tắt | **Build tương tự** — hợp memory/audit của my-crew. Pattern "search→summarize, không dump raw". |
| **reddit/youtube/facebook-group** (OpenClaw script + skill) | Monitor nguồn nội dung (Playwright) | **Tích hợp chọn lọc** cho marketer/researcher. Là script bash → chạy được. |
| **academic-research** (OpenClaw, OpenAlex 250M paper, free) | Tra cứu paper học thuật | **Copy skill** (markdown, no-key) cho researcher-pack. |

### B. Ghi/hành động ra ngoài (WRITE) — BẮT BUỘC qua Action Gateway

| Công cụ | Làm gì | my-crew |
|---|---|---|
| **gws-gmail-send / docs-write / sheets-append** (OpenClaw) | Gửi mail, ghi Doc/Sheet | **Build lại qua Gateway** — mỗi write = `_MUTATING_TYPE` + allowlist + handler. KHÔNG copy trực tiếp (bỏ qua gateway). |
| **goodreads-write / typefully / discord / feishu** | Đăng nội dung ra dịch vụ | Tương tự — chỉ build khi có nghề cần, luôn qua Gateway + Lớp B (external). |
| **send_message** (Hermes cross-channel) | Ping kênh/người khác | **Build tương tự** nếu my-crew đa kênh; qua Gateway. |

### C. Điều phối agent / tự động hoá — my-crew ĐÃ MẠNH, tham khảo có chọn

| Công cụ | Làm gì | my-crew |
|---|---|---|
| **delegate/subagent** (cả 2 hệ) | Giao việc con context sạch | my-crew đã có coordinator+PIC+peer-review (mạnh hơn). Nếu cần in-agent fan-out → LangGraph subgraph, KHÔNG fork process. |
| **cronjob tool** (Hermes) | Agent tự tạo reminder/digest | **Build tương tự** — "1 action-tool nén"; hook vào ticker coordinator. |
| **wake-gate / no_agent** (Hermes cron) | Watcher rẻ: poll, chỉ đánh thức LLM khi có thay đổi | **Build tương tự (ROI cao)** — cắt cost fleet. ~40 dòng trong coordinator. |
| **kanban tools** (Hermes) | Tạo/move/complete card | **Build** — mặt PM native, hợp office UI đã có. |
| **clarify (native buttons)** (Hermes) | Hỏi lại "dự án nào?/duyệt?" render nút | **Build** — agent hay cần hỏi CEO; render Telegram/web. |

### D. Chạy code / máy tính — CẨN TRỌNG (my-crew đang làm ở DeepAgent sandbox)

| Công cụ | Làm gì | my-crew |
|---|---|---|
| **code_execution / exec / terminal** (cả 2 hệ) | Chạy shell/code | my-crew CỐ Ý không có cho agent nghiệp vụ. Chỉ DeepAgent (sandbox Docker, đang harden). **KHÔNG mở rộng exec cho agent thường** = điểm mạnh an toàn. |
| **computer_use / browser automation** (cả 2) | Điều khiển desktop/browser | **Bỏ qua v1** — nặng, rủi ro, off-domain. |
| **osv_check / tirith_security** (Hermes) | Scan supply-chain/security | Tham khảo nếu my-crew cho cài pack cộng đồng (guard skill/tool ngoài). |

### E. Memory / học — my-crew có seam riêng (my-kioku v19.5)

| Công cụ | Làm gì | my-crew |
|---|---|---|
| **memory-core + dreaming** (OpenClaw) / **memory 8-provider + background-review + curator** (Hermes) | Nhớ dài hạn + consolidation | my-crew có seam `MemoryProvider` (kioku deferred). Tham khảo **pattern background-review** (whitelist tool + "do NOT capture" prompt) bọc quanh `reflect`. |
| **skill curator auto-archive** (Hermes) | Archive skill agent-tạo cũ theo tuổi | **Build tương tự** khi có skill động; chống rot. |

### F. Tích hợp chuẩn mở — nền tảng community

| Chuẩn | Cả 2 hệ dùng | my-crew |
|---|---|---|
| **MCP** (Model Context Protocol) | Host tool bên thứ 3 (Drive/Slack/…) | **my-crew ĐÃ có + đã harden**: `mcp_adapter.py` + session-pool (v11) + spawn-gate allowlist (`pack_mcp_gate.py`). Thêm server = khai pack.yaml. |
| **agentskills.io** (SKILL.md markdown) | Skill portable | **ĐÃ HỖ TRỢ từ v20** — `skill_loader.py` load cả flat `<name>.md` VÀ `<slug>/SKILL.md`. Còn thiếu: review-gate skill cộng đồng (Q3). |
| **Multi-provider model** (openrouter/anthropic/ollama/zai — cả 2) | Đổi model dễ | my-crew hiện OpenRouter-only. Tham khảo abstraction nếu cần local/multi-provider sau. |

---

## 3. Khuyến nghị ưu tiên cho my-crew

**Tích hợp NGAY (portable, hợp nghề office):**
1. **MCP host mạnh** + **skill-loader agentskills.io** → 2 ổ cắm mượn công cụ cộng đồng.
2. **Google Workspace** (gws) qua pack ToolProvider — admin/HR cần.
3. **Firecrawl** (đã dựng) — researcher/marketer.

**Build tương tự (ROI cao, ~ít dòng):**
4. **wake-gate/no_agent watcher** — cắt cost fleet.
5. **clarify (native buttons)** + **cronjob tool** + **kanban tool** — mặt office.
6. **session-search** (search→summarize) — hợp audit.

**Bỏ qua / giữ nguyên (đúng moat):**
- KHÔNG mở exec/computer-use/browser cho agent nghiệp vụ (giữ ở DeepAgent sandbox).
- KHÔNG copy tool WRITE trực tiếp — build lại qua Action Gateway.
- KHÔNG copy tool Python khoá-registry — chỉ mượn skill(markdown)/MCP/script.

---

## 4. Câu hỏi mở
1. ~~Nghề nào làm trước~~ **ĐÃ CHỐT (CEO 2026-07-12): hạ tầng chung trước** — wake-gate / cronjob-tool / kanban-tool / clarify (phục vụ mọi agent); nghề-specific (gws write → academic-research → reddit/youtube) sau khi có nhu cầu thật.
2. gws CLI: **đề xuất giữ subprocess** (tiền lệ `gh`/`gws` chạy tốt, credential env-only) — chốt cuối khi làm gws write.
3. Skill cộng đồng cần review-gate (chống injection) — chưa cần khi copy skill tự-chọn; cần khi mở marketplace → milestone riêng.
