# Project Overview & PDR — my-project-manager

> Product Definition / Requirements. Đọc file này TRƯỚC khi plan hay code.
> Status: **Vision + guardrail đã hiện thực hoá đầy đủ (Phase 0–5 complete).** Các "câu hỏi mở" ở §9
> đã được trả lời trong quá trình build — xem ghi chú resolved cuối §9.

## 1. Problem

Team AI-native. Nhóm **Dev đã có bộ công cụ AI khá hoàn chỉnh** để tự động hóa công việc. Nhóm **Management (PM / SM / Team Lead / …) thì CHƯA** — vẫn làm thủ công các việc lặp, tốn người:

- Đặt objective / OKR cho team.
- Monitoring metric (tiến độ, velocity, burndown, cost…).
- Viết report (status, sprint review, stakeholder update).
- Quản lý tiến độ, resource, cost.
- Quản lý stakeholder (cập nhật, giải trình).

Tất cả công việc trên đi qua 4 công cụ: **Slack, Confluence, Jira, GitHub**.

## 2. Goal

Xây 1 **agent (LangGraph) thay thế hoặc giảm ~90% cost** của các vai management trong team — tự động hóa tối đa, một phần hoặc hoàn toàn, các công việc management nêu trên.

**Không phải** chatbot trả lời câu hỏi. Là agent **chủ động làm việc**: đọc trạng thái 4 công cụ → suy luận → hành động (report, cập nhật, cảnh báo) như một PM/SM thật.

## 3. Success metric

| Metric | Mục tiêu |
|---|---|
| % thời gian management thủ công cắt được | ≥ 90% cho các việc trong scope |
| Report định kỳ tự động | 100% không cần người viết tay |
| Độ chính xác báo cáo tiến độ | sát số liệu Jira/GitHub thật, ≤ sai số người làm |
| Thời gian từ "sự kiện" → "management aware" | gần real-time thay vì chờ standup/họp |

## 4. Scope

### 4.1 MVP (giai đoạn 1) — **Reporting + Progress Monitoring**

Vào trước vì ROI rõ, rủi ro thấp nhất, làm được ngay:

- **Đọc** Jira (issues, sprint, status, assignee) + GitHub (PR, commit, review, CI) → tổng hợp tiến độ.
- **Phát hiện** rủi ro tiến độ: task quá hạn, PR treo, sprint lệch burndown, blocker.
- **Viết** report (status / sprint summary) và **đăng** lên Slack + Confluence.
- Chạy theo lịch (cron: daily standup digest, weekly sprint report) + on-demand.

### 4.2 Phase sau (đã biết, chưa làm)

- OKR / objective setting + map xuống Jira epic + track OKR progress.
- Resource management (capacity, allocation).
- Cost monitoring + budget alert.
- Stakeholder management (update tự động theo audience).

### 4.3 Out of scope (hiện tại)

- Thay thế quyết định chiến lược của con người (agent đề xuất, người chốt những việc nhạy cảm).
- Code review chất lượng sâu (đã thuộc bộ tool Dev).
- HR / performance review cá nhân.

## 5. Người dùng & cách dùng

- **Giai đoạn đầu**: chạy **CLI / local**, 1 người dùng (chủ dự án), chưa multi-user. Đơn giản hóa để ra MVP nhanh.
- **Scale sau**: service backend + Slack làm UI chính (slash command / mention / DM), cron report định kỳ. Kiến trúc phải để ngỏ đường lên đây (xem system-architecture.md).

## 6. Quyết định kiến trúc đã chốt (2026-06-21)

| Quyết định | Chốt | Ghi chú |
|---|---|---|
| Framework | **LangGraph (Python)** | Ecosystem agent giàu nhất; khớp DeerFlow (ref ở `~/workspace/deer-flow`); SDK công cụ sẵn. |
| Runtime giai đoạn 1 | **CLI / local** | Scale lên service + Slack UI sau. |
| MVP scope | **Reporting + progress monitoring** | OKR/resource/cost/stakeholder là phase sau. |
| Write authority | **Full autonomous write** | ⚠️ Xem cảnh báo §7 — autonomous KHÔNG có nghĩa không phanh. |
| Công cụ | Slack, Confluence, Jira, GitHub | Đọc tất cả; write theo §7. |

## 7. ⚠️ Guardrail cho "Full autonomous write" (BẮT BUỘC đọc)

Chốt là agent **tự ghi** (tạo Jira ticket, post Slack, sửa Confluence) không cần human-in-the-loop duyệt từng hành động. Đây là lựa chọn rủi ro cao. Để autonomous không thành "không phanh", agent kế tiếp PHẢI implement lớp guardrail sau **ngay từ MVP**:

1. **Audit log bất biến** — mọi write (tool, tham số, kết quả, timestamp, lý do agent quyết định) ghi log không xóa được. Không có audit = không được write.
2. **Dry-run mode mặc định khi dev** — env flag `DRY_RUN=true` → agent log "định làm gì" thay vì làm thật. Bật write thật phải explicit.
3. **Kill switch** — 1 lệnh / 1 env flag tắt toàn bộ write ngay lập tức. Document rõ cách dùng.
4. **Scoped tokens** — token mỗi công cụ giới hạn quyền tối thiểu cần (vd GitHub không cần admin; Jira chỉ project liên quan). KHÔNG dùng token full-access.
5. **Rate / blast-radius limit** — cap số write / phút (chống loop spam ticket). Confluence: sửa có version, không ghi đè mù.
6. **Idempotency** — không post trùng report, không tạo trùng ticket khi re-run (dùng marker / dedup key).
7. **Reversibility ưu tiên** — ưu tiên hành động đảo ngược được (comment thay vì xóa; tạo draft thay vì publish khi nhạy cảm).
8. **Budget cap = $50/tháng (OpenRouter)** — track cost cộng dồn (per-run + cộng dồn tháng). Cảnh báo ở 80%, **hard-stop ở 100%**: chạm trần → từ chối LLM call mới, log + báo, không âm thầm chạy tiếp. Reset đầu tháng.

### 7.9 Ranh giới autonomous — 2 lớp (CHỐT 2026-06-21)

Dù "full autonomous", có 2 lớp KHÔNG được tự ý làm:

**🚫 Lớp A — CẤM TUYỆT ĐỐI (hard-block, agent không bao giờ làm, kể cả khi LLM "muốn"):**
- Xóa/ghi đè gây **mất data vĩnh viễn**: `git push --force`, xóa commit/branch/tag, xóa Jira issue, xóa/ghi đè trang Confluence không qua version, xóa file backup tài liệu, `rm` data.
- Bất kỳ thao tác **credential**: đọc rồi gửi token/key/secret ra ngoài (Slack message, Jira comment, Confluence page, HTTP request tới đích lạ, log không che). KHÔNG echo secret ra bất kỳ output nào.
- Bất kỳ hành động tạo **security incident**: cấp quyền, đổi permission/visibility (public hóa repo/page private), mời người ngoài, tắt security setting, expose internal data ra public.
→ Những cái này hard-code chặn ở Action Gateway, KHÔNG phải để LLM quyết. Vi phạm = bug nghiêm trọng nhất.
> **Lưu ý integration (CHỐT 2026-06-21)**: hành động đi qua **MCP tool** (Jira/Confluence/Slack server) hoặc **`gh` CLI** (GitHub; sau: GWS CLI). Gateway hard-block phân loại theo **MCP tool name + args** và **`gh` command line**, không phải SDK Python. Đặc biệt: **Slack dùng browser-token** (rộng quyền hơn bot-token scoped) → siết kỹ ở rule credential + chỉ post vào channel cho phép.

**⏸️ Lớp B — PHẢI HỎI NGƯỜI (interrupt node, dừng chờ approve dù autonomous):**
- Hành động khó đảo ngược nhưng đôi khi cần thật: hủy/đóng ticket, đổi scope sprint, message tới **stakeholder external / khách hàng**, đổi assignee người thật, đóng/merge PR.
→ Agent đề xuất + nêu lý do, người chốt. Danh sách này có thể mở rộng — ghi vào `system-architecture.md §5.2`.

> Nguyên tắc: autonomous về **tốc độ**, không autonomous về **trách nhiệm**. Mất-data-vĩnh-viễn và security là LẰN RANH ĐỎ — chặn cứng, không thương lượng. Mọi hành động phải truy vết và dừng được.

## 8. Bối cảnh hệ sinh thái (để agent kế tiếp định vị)

Dự án này nằm trong workspace cá nhân học + xây agent framework. Tham khảo có sẵn trên máy:
- `~/workspace/deer-flow` — DeerFlow 2.0 (ByteDance), harness production **xây trên LangGraph**. Dùng làm reference patterns (sub-agent executor, middleware, memory). KHÔNG copy thẳng.
- `~/workspace/openclaw-workspace` — admin hub, KB OpenClaw/Hermes. Repo này (`my-project-manager`) là **độc lập**, không phụ thuộc OpenClaw.

## 9. Quyết định & câu hỏi mở

### Đã chốt (2026-06-21)

- **Credentials**: ✅ Có **Atlassian Cloud thật** (Jira project + Confluence space), **Slack thật**, **GitHub thật**. Build/test trên instance thật ngay, KHÔNG mock. → Cần token scoped (xem `deployment-guide.md §3`).
- **Integration (CHỐT 2026-06-21)**: Jira/Confluence/Slack qua **MCP server có sẵn** (Node stdio, repo riêng ở `~/workspace/*-mcp-server`), agent là MCP client (`langchain-mcp-adapters`). GitHub qua **`gh` CLI**; tương lai **GWS qua CLI**. KHÔNG dùng SDK Python trực tiếp (atlassian-python-api/slack-sdk/PyGithub). Chi tiết: `system-architecture.md §4`. Atlassian token (email + API token) cấp cho MCP server, không cho agent Python.
- **LLM provider**: ✅ **OpenRouter** (để test nhiều model dễ). Mặc định `minimax/minimax-m2.7`; fallback `qwen/qwen-3.7` nếu m2.7 không hiệu quả. → Tầng `llm/` phải provider-agnostic + model đổi qua config, KHÔNG hardcode. Reuse pattern OpenRouter (base_url `https://openrouter.ai/api/v1`, OpenAI-compatible).

- **OpenRouter budget**: ✅ **$50/tháng**. Agent build PHẢI track cost cộng dồn + hard-stop khi chạm trần (xem §7.8). m2.7 rẻ nên $50 là dư cho MVP, nhưng autonomous loop lỗi có thể đốt nhanh → cap là bắt buộc.
- **Ranh giới "autonomous"**: ✅ Đã định nghĩa rõ — xem §7.9 (danh sách hành động CẤM / PHẢI hỏi người).

### Đã trả lời trong quá trình build (resolved)

1. **Ngưỡng "tiến độ tốt/xấu"** → ✅ Rule cụ thể, ngưỡng config được: overdue theo due-date, PR stale
   `PR_STALE_DAYS` (default 7), blocker theo label, overload theo bội số trung bình team
   `RESOURCE_OVERLOAD_RATIO` (default 1.5). Xem `risk_analyzer.py` + `resource_analyzer.py`.
2. **Report format** → ✅ Agent tự sinh: số liệu render deterministic (không để LLM bịa), LLM chỉ viết
   prose; Slack mrkdwn + Confluence XHTML storage. Xem `src/llm/*_report_prompt.py`.
3. **Audience report** → ✅ Làm ở Phase 5: `--audience internal|external`; external qua Lớp B duyệt.
4. **Single vs multi-project** → ⏸️ Vẫn **single-project** (1 `JIRA_PROJECT_KEY`/`GITHUB_REPO`).
   Multi-project/multi-user là phần **defer** cùng service backend (xem roadmap "deferred").
