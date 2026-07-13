# Gợi ý bổ sung lõi agent-harness my-crew (từ OpenClaw + Hermes)

**Ngày:** 2026-07-13 · **Cơ sở:** my-crew v37 (2148 test pass) + inventory OpenClaw/Hermes.
**Mục tiêu:** làm lõi harness **mạnh + đa dụng hơn** mà KHÔNG yếu guardrail.
**Nguồn:** gap-map đọc code v37 thật, đối chiếu năng lực OpenClaw/Hermes.

---

## 0. Bối cảnh: v37 đã hấp thụ phần lớn gợi ý cũ

**ĐÃ DONE (đừng đề xuất lại):** wake-gate watcher · memory consolidation (dreaming-like) · per-attempt telemetry/cost 3 engine · Firecrawl · MCP adapter+gate · skill-loader agentskills.io (`<slug>/SKILL.md`) · trust_mode (autonomous/guarded) · sandbox hardening (F1–F5 đã vá) · heartbeat · **clarify native buttons** · **FTS5 session/history search + summarize** · cron/scheduler · exec-approvals · follow-up sweep · office rooms · peer-review · lease coordination · multi-channel delivery.

→ Harness đã **rất đủ**. Phần dưới chỉ là các gap THẬT còn lại, xếp theo (giá trị × hợp-invariant).

---

## 1. TOP 6 bổ sung (nên làm — mạnh hơn/đa dụng hơn, giữ nguyên moat)

### #1 — `send_message` gateway action-type (ROI/effort cao nhất) ⭐
**Gap:** delivery hiện chỉ dạng report (`channel_registry`) + reply. CHƯA có "agent chủ động gửi X tới kênh/người Y" tổng quát.
**Nguồn:** Hermes `send_message` cross-channel.
**Vì sao đa dụng:** mọi nghề (admin nhắc lịch, HR gửi thông báo, marketer đăng bài) cần "chủ động gửi". Đây là primitive thiếu để agent thật sự "làm việc ra ngoài" ngoài báo cáo định kỳ.
**Effort:** THẤP — thêm 1 action-type qua `action_gateway`, tái dùng writer sẵn (slack/telegram/email/confluence).
**Invariant:** SẠCH — đi qua gateway = tự động guardrail (Lớp A/B + audit + trust_mode). Không bề mặt egress mới.

### #2 — Skill curator + usage-tracking + auto-archive
**Gap:** có loader/selector nhưng KHÔNG theo dõi skill nào dùng, không prune skill chết, không provenance.
**Nguồn:** Hermes skill curator + provenance + usage-tracking.
**Vì sao đa dụng:** harness community sẽ tích luỹ nhiều skill; không có curator → thư viện skill mục ruỗng, selector chọn nhiễu.
**Effort:** THẤP-TB — 1 counter ghi từ `skill_selector` + sweep archive định kỳ (mirror `consolidation.py` đã có).
**Invariant:** SẠCH — pure internal state, no egress.

### #3 — Multi-provider model routing (không chỉ OpenRouter)
**Gap:** `client.py` OpenRouter-only (1 base URL).
**Nguồn:** OpenClaw (anthropic/ollama/zai/local), Hermes 30 provider.
**Vì sao đa dụng:** mở **local/offline** (privacy — dữ liệu công ty không rời máy) + **cost arbitrage** + resilience khi 1 provider chết (đã có fallback_policy nhưng cùng OpenRouter).
**Effort:** TB — abstraction provider dưới `LlmClient`, route per-model.
**Invariant:** SẠCH — telemetry/pricing seam đã provenance-aware, chỉ thêm nguồn. (Đây là hướng v4 "local-first" trong ghi chú cũ.)

### #4 — OSV/dep-scan khi cài pack & skill cộng đồng
**Gap:** `pack_mcp_gate` chặn spawn binary độc, nhưng KHÔNG scan nội dung pack/skill (dep known-vuln, code độc).
**Nguồn:** Hermes osv_check / tirith_security.
**Vì sao đa dụng:** pack/skill cộng đồng = **bề mặt untrusted chính** của harness khi mở community. Đây là điều kiện an toàn để nhận đóng góp ngoài.
**Effort:** TB — hook scan (osv/bandit) vào pack/skill install path + review-gate.
**Invariant:** XUẤT SẮC — mở rộng đúng trust boundary community-socket.

### #5 — Background-review: forked sub-run bound to `read_only_toolset`
**Gap:** consult hiện là read-only role-play trên file persona, KHÔNG phải worker fork thật với toolset hạn chế.
**Nguồn:** Hermes `background_review` (fork + whitelist memory/skill tool).
**Vì sao đa dụng:** self-critique thật (agent tự soi lại việc mình trước khi giao) → chất lượng cao hơn. Ngành coi verification = 2-3x quality.
**Effort:** TB.
**Invariant:** TỐT — fork bind vào `read_only_toolset` (moat sẵn của tool-calling runtime), 0 egress mới. **Steal prompt "do NOT capture" của Hermes.**

### #6 — Write-back memory provider tier (semantic/FTS recall)
**Gap:** `MemoryProvider.record` là no-op; chỉ static + consolidation. Seam có nhưng chưa thành năng lực.
**Nguồn:** Hermes 8 memory provider (semantic/FTS). (my-kioku là ứng viên — đã có engine.)
**Vì sao đa dụng:** agent nhớ ngữ cảnh dài → làm việc tốt hơn qua thời gian.
**Effort:** TB.
**Invariant:** CẦN CẨN TRỌNG — provider write-back phải **internal-audience-only**, external run KHÔNG được đọc internal memory (red line #2). Ưu tiên thấp hơn #1–#4 vì đụng invariant nhạy nhất.

**(Phụ) #7 — `todo`/scratch-list trong 1 step** — THẤP effort, sạch, nhưng giá trị khiêm tốn (DAG decomposition đã lo phần lớn). Làm nếu có step dài.

---

## 2. Thứ tự đề xuất

**Đợt 1 (rẻ + đa dụng ngay):** #1 send_message → #2 skill curator.
**Đợt 2 (mở rộng nền tảng):** #4 OSV-scan (điều kiện mở community) → #3 multi-provider (local/offline).
**Đợt 3 (chất lượng/chiều sâu):** #5 background-review → #6 write-back memory.

---

## 3. ⛔ 3 thứ KHÔNG nên thêm (dù OpenClaw/Hermes có)

1. **computer_use / live browser automation** — browser sống = **kênh egress có state, KHÔNG qua gateway** → phá thẳng invariant gateway-only-egress + external=zero-memory. **Invariant-fatal.** (Cần scrape web → dùng Firecrawl đã có, qua tool có kiểm.)
2. **mixture_of_agents** — nhân cost mỗi tick, ROI yếu; DAG + peer-review + consult đã phủ nhu cầu multi-agent synthesis. Trái ethos wake-gate/budget-cap.
3. **host-shell / local-shell runtime tier** — code đã cố ý từ chối `local/localshell` (red-team C3). Thêm host-shell "cho tiện" = chạy lệnh với token CEO **dưới** gateway. Giữ shell chỉ trong sandbox.

---

## 4. Nhận định tổng

Lõi harness my-crew v37 **đã ngang tầm** các harness trưởng thành (OpenClaw/Hermes) ở hầu hết trục, và **vượt** ở guardrail (gateway-only + trust-mode + sandbox-sanitizer). 6 gap còn lại là **làm giàu**, không phải vá thiếu sót nền tảng. Ưu tiên #1 (send_message) + #2 (curator) vì rẻ và đa dụng tức thì; #4 (OSV) là điều kiện an toàn để đi community.

**Nguyên tắc vàng giữ nguyên:** mỗi bổ sung phải (a) mọi egress qua Action Gateway, (b) không cho external-audience đọc internal, (c) không mở shell ngoài sandbox, (d) internal-state không qua gateway. Cả 6 đề xuất trên đều thoả.

---

## 5. Câu hỏi mở
1. **Local/offline model (#3)** có phải yêu cầu thật (privacy dữ liệu công ty) hay chưa cần? Quyết định ưu tiên #3.
2. **Mở community pack/skill** khi nào? → quyết định độ gấp của #4 (OSV) + review-gate.
3. **Write-back memory (#6)** dùng my-kioku (engine sẵn) hay LangGraph Store semantic? Cần đo recall trước khi chốt (đã bàn ở tài liệu nhánh-D trước).
4. `trust_mode=autonomous` default + `send_message` (#1): agent tự gửi ra ngoài không hỏi — với community/multi-user nên default `guarded`? Cần chốt cùng #1.
