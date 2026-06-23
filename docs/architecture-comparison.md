# Architecture & Safety Comparison — my-project-manager vs reference harnesses

> Đánh giá kiến trúc + mô hình an toàn (guardrail / write-authority) của `my-project-manager`,
> đặt cạnh 3 harness tham khảo: **DeerFlow 2.0**, **Hermes-agent**, **OpenClaw / Pi.dev**.
> Mục tiêu: định vị trung thực — repo này MẠNH chỗ nào, NHẸ chỗ nào, và *vì sao* khác biệt.
>
> Phương pháp: DeerFlow + Hermes khảo sát ở mức **code** (đọc source); OpenClaw/Pi.dev chỉ có
> **docs/notes** trên máy (không có source engine) → đánh giá ở mức *khái niệm*, ghi rõ giới hạn.
> Số liệu của repo này verify trực tiếp từ `src/` (2026-06-23).

---

## 0. TL;DR — một bảng

| | **my-project-manager** | **DeerFlow 2.0** | **Hermes-agent** | **OpenClaw / Pi.dev** |
|---|---|---|---|---|
| Thể loại | PM agent dọc (vertical), MVP local-first | General multi-agent harness, production | General personal agent, production | Personal agent platform (Telegram-first) |
| Core size | **~5.2k LOC / 47 file** | ~40.5k LOC core | ~25–40k LOC core | (no source — docs only) |
| Orchestration | **LangGraph StateGraph tường minh** (perceive→analyze→compose→deliver) | LangGraph + 23-lớp middleware + `create_agent` loop | ReAct while-loop (không graph) | Custom harness (Pi.dev), gateway+session loop |
| Multi-agent | **Không** (single graph, có chủ đích) | Có (subagent executor, ≤3 concurrent) | Có (delegate, ≤3, blocking) | Có (delegate, ≤3, blocking) |
| **Safety model** | **Gate-each-action: Action Gateway = 1 choke-point, policy theo từng action** | Sandbox-first + optional policy middleware + observability | OS-isolation + in-process heuristics (không phải boundary) | **Persona-prompt (SOUL.md), KHÔNG harness-enforce** |
| Hard-deny red line | **✅ Lớp A hard-coded, không bao giờ tới LLM** | ⚠️ Không có blocklist mặc định; allowlist qua config | ⚠️ 12 hardline pattern (rm /, mkfs…) + 47 denylist regex | ❌ Không (chỉ prompt) |
| Human-in-the-loop | **✅ Lớp B queue + approve, execute thật** | ⚠️ Clarification interrupt (hỏi lại), không phải approval-to-execute | ⚠️ Approval gate (configurable, không bắt buộc) | ⚠️ Manual draft→"ok" (prompt-level) |
| Audit log | **✅ JSONL append-only + redact secret** | ✅ RunEventStore (SQL) | ❌ Không audit; lưu full transcript không redact | ⚠️ "verified actions" = test thủ công, không phải log |
| Budget cap | **✅ $50/tháng hard-stop** | ⚠️ Token usage track, không hard cap | ⚠️ Per-turn iteration budget | — |
| Dedup / idempotency | **✅ reserve-before-execute (SQLite)** | ❌ (dựa checkpointer retry) | ❌ | — |
| Sandbox | **❌ không** (đánh đổi có chủ đích) | ✅ per-thread FS + Docker option | ✅ OS-level (container/VM) là boundary chính | ⚠️ "varies by project" |
| Checkpointer | SQLite (state chỉ primitive) | SQLite→Postgres, per-thread | git-style snapshot (không resume giữa turn) | `.jsonl` session + auto-compact |

**Một câu:** Repo này là **MVP nhỏ nhất nhưng có mô hình kiểm soát write CHẶT NHẤT** trong 4 cái. Ba
harness kia lớn hơn nhiều và mạnh hơn về *năng lực tổng quát* (sub-agent, sandbox, multi-channel,
memory), nhưng **không cái nào đặt "mọi mutation qua 1 cổng policy-gated với red line hard-coded"** làm
trục kiến trúc. Đó vừa là điểm khác biệt, vừa là điểm đánh đổi.

---

## 1. Bối cảnh: so cái gì với cái gì (apples vs oranges)

Phải nói thẳng để so cho công bằng: **không cùng hạng cân.**

- **my-project-manager** là agent **dọc** (làm 1 việc: PM reporting), **local-first MVP**, single-agent.
- **DeerFlow / Hermes** là harness **ngang** (general-purpose, chạy mọi loại task), production, multi-agent,
  multi-channel. To gấp ~5–8 lần về code.
- **OpenClaw / Pi.dev** là platform personal-agent, engine đóng (chỉ đánh giá qua docs).

→ Vì vậy so **năng lực tổng quát** thì repo này *kém* (đúng — nó không định làm general). So **mô hình an
toàn cho autonomous write** thì repo này có cái 3 harness kia *không có*. Phần dưới tách rõ 2 trục bạn chọn.

---

## 2. Trục 1 — Guardrail / Safety / Write-authority (điểm khác biệt cốt lõi)

### 2.1 Bốn triết lý an toàn khác nhau

| Harness | Triết lý an toàn (rút từ code/docs) |
|---|---|
| **my-project-manager** | **Gate-each-action by policy.** Mọi mutation qua `ActionGateway.execute`. Chuỗi: Lớp A hard-deny → Lớp B approve → kill-switch → dry-run → rate-limit → dedup → execute → audit. Red line (data-loss/credential/security) **hard-coded, không tới LLM**. |
| **DeerFlow 2.0** | **Sandbox-first + optional policy + observability.** Cô lập filesystem per-thread (+ Docker option). `GuardrailMiddleware` là *tùy chọn* (bật qua config), provider pluggable (allowlist/denylist). Không có blocklist nguy hiểm mặc định. `SafetyFinishReasonMiddleware` bắt tín hiệu safety của *provider* (content_filter/refusal) rồi chặn tool call. |
| **Hermes-agent** | **OS-isolation là boundary, in-process chỉ là heuristic.** SECURITY.md nói thẳng: chỉ container/VM mới là ranh giới thật; approval pattern + loop-detection KHÔNG phải containment, "một LLM đối kháng hoặc nội dung bị inject có thể vượt qua hết". Có 12 hardline pattern chặn cứng (rm /, mkfs, reboot…) + 47 denylist regex. |
| **OpenClaw / Pi.dev** | **Persona-prompt, không harness-enforce.** An toàn nằm ở SOUL.md/MEMORY.md ("luôn show draft trước khi post", "hỏi trước khi gửi email"). Pi.dev harness **không gate tool call**. "Verified actions" = đã test thật thủ công, không phải pre-action gating. |

### 2.2 Khác biệt then chốt: choke-point vs middleware vs prompt

- **my-project-manager**: **một** choke-point. Không module nào gọi API write trực tiếp — nếu thấy là bug.
  Code: [`src/actions/action_gateway.py`](../src/actions/action_gateway.py) (`_execute` = cả chuỗi).
- **DeerFlow**: guardrail là **một lớp trong 23 lớp middleware**, và *tùy chọn*. Nếu config không bật
  `guardrails.enabled`, không có policy gating — chỉ còn sandbox + observability. Mạnh ở chỗ pluggable +
  fail-closed; yếu ở chỗ "secure-by-default" không phải mặc định.
- **Hermes**: guardrail là **regex denylist trên shell command** + OS sandbox. Hermes tự thừa nhận denylist
  trên shell (Turing-complete) là "structurally incomplete". Triết lý: đừng tin in-process, hãy cô lập OS.
- **OpenClaw**: **không có tầng enforce** — an toàn là chất lượng prompt (SOUL.md).

### 2.3 Cái repo này có mà 3 harness kia KHÔNG (hoặc yếu hơn)

1. **Lớp A red-line hard-coded, không bao giờ tới LLM.** DeerFlow không có blocklist mặc định; Hermes có
   hardline nhưng chỉ cho *shell*, không cho mọi tool; OpenClaw không có. → Repo này là cái duy nhất mà
   "xóa branch / lộ token / public hóa repo" bị chặn ở *kiến trúc*, không phải ở *chỉ dẫn cho LLM*.
2. **Allowlist-default-deny cho MỌI tool** (không chỉ shell). Chuyển từ denylist sau khi review đối kháng tìm
   bypass thật (xem journal Phase 0). DeerFlow allowlist là opt-in; Hermes là denylist.
3. **Lớp B approve-to-EXECUTE.** DeerFlow `ClarificationMiddleware` chỉ *hỏi lại rồi END*; Hermes approval
   *configurable, không bắt buộc*; OpenClaw là draft-rồi-người-gõ-"ok" ở mức prompt. Repo này: action bị
   queue, người `approve <id>`, rồi **gateway thật sự execute** action đã duyệt (vẫn qua Lớp A + audit).
4. **Secret redaction dùng CHUNG** cho gateway-block = audit-redact = approval-store (1 nguồn, không lệch).
   Hermes lưu full transcript không redact; DeerFlow không có tầng redact global.
5. **Budget hard-stop + dedup reserve-before-execute.** DeerFlow track token nhưng không hard cap; cả 3 đều
   không có idempotency dedup kiểu reserve-before-execute.

### 2.4 Cái repo này KHÔNG có mà 3 harness kia có (đánh đổi trung thực)

1. **Sandbox.** Đây là khác biệt lớn nhất theo hướng ngược lại. DeerFlow + Hermes coi **OS-isolation là
   ranh giới an toàn THẬT**; repo này **không có**. Hệ quả: repo này an toàn *vì phạm vi hành động hẹp*
   (chỉ post Slack/Confluence qua allowlist), KHÔNG vì cô lập môi trường. Nếu mở rộng sang shell/code-exec
   thì *bắt buộc* phải thêm sandbox — Action Gateway một mình không đủ.
2. **Bảo vệ trước prompt-injection / adversarial LLM.** Hermes nói thẳng in-process gating không chống được
   LLM đối kháng. Action Gateway của repo này CŨNG vậy ở tầng *nội dung* (LLM vẫn có thể viết bậy vào prose)
   — nhưng tầng *action* thì red-line hard-coded chặn được (LLM không chọn được việc xóa branch). Phòng thủ
   của repo này là "phạm vi action hẹp + allowlist", không phải "cô lập kẻ tấn công".
3. **Provider safety-signal handling.** DeerFlow bắt content_filter/refusal của provider; repo này không.

### 2.5 Kết luận trục 1

> Về **kiểm soát autonomous write cho một agent dọc, phạm vi hẹp**, mô hình Action Gateway của repo này
> **chặt và tường minh hơn** cả ba — nó là cái duy nhất biến red line thành bất biến *kiến trúc* (hard-coded,
> trước LLM) thay vì *chính sách tùy chọn* (DeerFlow), *heuristic shell* (Hermes), hay *prompt* (OpenClaw).
>
> Nhưng đây là an toàn **theo chiều sâu hẹp**: nó mạnh vì agent chỉ làm vài việc đã allowlist. Ba harness kia
> giải bài toán **rộng** (chạy code/shell tùy ý) nên buộc phải dựa vào **sandbox/OS-isolation** — thứ repo
> này cố tình không làm (YAGNI cho MVP local). Hai cách tiếp cận trả lời hai câu hỏi khác nhau:
> *"làm sao agent không vượt red line?"* (gateway) vs *"làm sao cô lập agent khỏi hệ thống?"* (sandbox).
> Một agent general production cần **cả hai**.

---

## 3. Trục 2 — Kiến trúc agent-core

### 3.1 Orchestration

| | Mô hình | Đánh giá |
|---|---|---|
| **my-project-manager** | LangGraph StateGraph **tường minh**: `perceive→analyze→compose→deliver`, node cố định, không có agentic-loop ẩn. | Mọi bước agent quyết định *nhìn thấy được trong graph*. Dễ test, dễ audit, dễ resume. Đánh đổi: kém linh hoạt cho task mở (agent không "tự nghĩ ra bước"). Hợp với agent dọc, lịch trình. |
| **DeerFlow** | LangGraph + `create_agent` (tool-calling loop) + 23 lớp middleware có thứ tự. | Loop linh hoạt (agent tự chọn tool tới khi xong) + middleware tách concern (sandbox, memory, guardrail, summarize…). Mạnh, nhưng nặng: thứ tự 23 lớp là một API mặt phải hiểu. |
| **Hermes** | ReAct while-loop thuần (không graph). | Đơn giản về cấu trúc, nhưng `conversation_loop.py` ~3,900 dòng — logic dồn vào một loop lớn. Không resume-giữa-turn. |
| **OpenClaw/Pi.dev** | Gateway HTTP + session loop, harness đóng. | Telegram-first, session `.jsonl` auto-compact. Khó đánh giá sâu (không source). |

**Nhận xét:** Repo này chọn **graph tường minh** đúng cho bài toán của nó (report theo lịch, các bước cố
định, cần audit + resume). DeerFlow chọn **loop + middleware** vì phải xử lý task mở. Đây không phải "ai
hơn ai" mà là "graph cho control-flow biết trước" vs "loop cho control-flow do LLM quyết". Repo này còn một
điểm kỷ luật đáng học: **state chỉ chứa primitive** (model nặng để trong closure) → checkpointer sạch,
không vỡ serialize — một lỗi DeerFlow phải xử lý bằng custom reducers.

### 3.2 Multi-agent

- **Repo này: KHÔNG sub-agent** — có chủ đích. 3 harness kia đều có delegate (≤3 concurrent). Với agent dọc
  một-luồng-report, sub-agent là over-engineering (YAGNI). Nhưng nếu sau này cần "fan-out nhiều project song
  song", đây là chỗ phải mượn pattern executor của DeerFlow/Hermes.

### 3.3 Tool layer

- **Repo này**: READ qua MCP (spawn stdio subprocess) + `gh` CLI; WRITE qua Action Gateway. Tách READ/WRITE
  rạch ròi — **mọi WRITE một đường, mọi READ một đường khác**. Đây là điểm kiến trúc gọn mà 3 harness kia
  không tách bạch bằng (chúng trộn tool trong một registry, an toàn dựa vào middleware/sandbox bọc registry đó).
- **DeerFlow/Hermes**: tool registry + function-calling; MCP là một nguồn tool trong nhiều nguồn. DeerFlow có
  MCP session pool + deferred-tool promotion (tinh vi hơn).

### 3.4 Model layer

- Cả 4 đều provider-agnostic. Repo này dùng **raw `openai` SDK trỏ OpenRouter** (giữ field `cost` để budget
  track) — đơn giản, một provider. DeerFlow/Hermes có **model factory đa provider + fallback** (Hermes hỗ trợ
  ~15 provider, switch giữa session). Đây là chỗ repo này tối giản nhất — đủ cho MVP, sẽ cần mở rộng nếu
  muốn multi-model.

### 3.5 Memory

- **Repo này: không có memory subsystem** (agent stateless giữa run, chỉ checkpoint graph state). 3 harness
  kia đều có memory persist (DeerFlow: LLM-extract→JSON; Hermes/OpenClaw: "memory dreaming"). Với agent
  report theo lịch, memory chưa cần (dữ liệu lấy tươi mỗi run từ Jira/GitHub). Sẽ cần nếu agent phải "nhớ
  quyết định cũ" xuyên report.

### 3.6 Kết luận trục 2

> Agent-core của repo này là **bản LangGraph tối giản, kỷ luật, đúng-vừa-đủ** cho một agent dọc: graph tường
> minh, state primitive-only, READ/WRITE tách lớp, single-agent. Nó **không** có (và không cần, ở giai đoạn
> này) các tầng nặng của harness production: sub-agent executor, sandbox, memory, multi-provider factory,
> middleware chain, multi-channel. Đó chính xác là khoảng cách MVP↔production — và repo này điều hướng khoảng
> đó *có chủ đích* (mỗi tầng nặng đều được hoãn với lý do YAGNI ghi rõ trong journals/roadmap).

---

## 4. Bài học rút ra (cho người build agent)

1. **"Mọi mutation qua 1 cổng" + "red line hard-coded trước LLM" là pattern mạnh và NHẸ** — repo này làm được
   trong ~1.2k LOC guardrail, không cần sandbox. Hợp cho agent **phạm vi action hẹp, đã biết trước**
   (report, post, comment). Đây là đóng góp dạy-học chính của repo.
2. **Nhưng gateway KHÔNG thay được sandbox** khi phạm vi action mở (shell/code-exec). DeerFlow + Hermes đúng
   khi coi OS-isolation là boundary thật. → Chọn cơ chế theo *bề rộng hành động*: hẹp→gateway đủ; rộng→cần
   sandbox; **production general cần cả hai**.
3. **Graph tường minh vs loop**: nếu control-flow biết trước (report theo lịch) → graph tường minh thắng về
   audit/test/resume. Nếu control-flow do LLM quyết (task mở) → loop+middleware như DeerFlow.
4. **State chỉ primitive** là kỷ luật nhỏ tránh được lớp phức tạp (custom reducer) mà harness lớn phải gánh.
5. **Approve-to-execute phải execute thật** — bài học Phase 5: một "approval" chỉ authorize mà không dispatch
   là approval giả. Cả Hermes có approval-gate thật; OpenClaw chỉ dừng ở draft-prompt.

---

## 5. Định vị một dòng

**`my-project-manager`** = *"agent dọc nhỏ nhất với mô hình kiểm soát write tường minh nhất"*. Nó không cạnh
tranh bề rộng với DeerFlow/Hermes/OpenClaw — nó **chứng minh một luận điểm**: có thể cho LLM full autonomous
write mà vẫn an toàn, **không cần sandbox**, nếu (a) phạm vi action hẹp + allowlist, (b) red line hard-coded
trước LLM, (c) mọi write qua 1 cổng có audit. Ba harness kia mạnh hơn nhiều về năng lực, nhưng **không cái
nào đặt luận điểm đó làm trục** — đó là lý do repo này đáng đọc như tài liệu học *về guardrail*, dù nhỏ.

---

## Unresolved / giới hạn của đánh giá này

1. **OpenClaw/Pi.dev chỉ đánh giá qua docs** (không có source engine trên máy) — kết luận về nó là *as
   documented*, có thể engine thật làm nhiều hơn docs ghi.
2. **Chưa benchmark hiệu năng/độ tin cậy thực tế** giữa 4 — so sánh ở mức kiến trúc + cơ chế, không phải số
   liệu chạy.
3. **DeerFlow/Hermes liên tục phát triển** — số liệu (LOC, số middleware) là snapshot tại thời điểm khảo sát.
