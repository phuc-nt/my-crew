# Architecture & Safety Comparison — my-project-manager vs reference harnesses

> Đánh giá kiến trúc + mô hình an toàn (guardrail / write-authority) của `my-project-manager`,
> đặt cạnh 3 harness tham khảo: **DeerFlow 2.0**, **Hermes-agent**, **OpenClaw / Pi.dev**.
> Mục tiêu: định vị trung thực — repo này MẠNH chỗ nào, NHẸ chỗ nào, và *vì sao* khác biệt.
>
> Phương pháp: cả 3 harness tham khảo khảo sát ở mức **code/source thật**. OpenClaw/Pi.dev là npm
> package cài trên máy (`/opt/homebrew/lib/node_modules/openclaw` v2026.6.1) — đọc được `dist/` +
> `.d.ts` type declarations + runtime `~/.openclaw/`. Số liệu của repo này verify trực tiếp từ `src/`.
>
> **⚠️ Đính chính (2026-06-23):** bản đầu của báo cáo này đánh giá OpenClaw "chỉ qua docs" và kết luận
> *"persona-prompt, không harness-enforce"* — **SAI**. Khi tìm thấy source thật (cài qua npm global, không
> phải `~/workspace`), OpenClaw hoá ra có **safety harness-enforced rất tinh vi** (exec-approval đa mode,
> SSRF guard, fs-safe, command-secret gateway). Toàn bộ phần OpenClaw đã viết lại theo source.

---

## 0. TL;DR — một bảng

| | **my-project-manager** | **DeerFlow 2.0** | **Hermes-agent** | **OpenClaw / Pi.dev** |
|---|---|---|---|---|
| Thể loại | PM agent dọc (vertical), MVP local-first | General multi-agent harness, production | General personal agent, production | General personal-agent platform (multi-channel), production |
| Core size | **~5.2k LOC / 47 file** | ~40.5k LOC core | ~25–40k LOC core | Rất lớn (npm package ~30 channel ext + plugin SDK) |
| Orchestration | **LangGraph StateGraph tường minh** (perceive→analyze→compose→deliver) | LangGraph + 23-lớp middleware + `create_agent` loop | ReAct while-loop (không graph) | Custom harness (Pi.dev) + plugin/channel-contract SDK |
| Multi-agent | **Không** (single graph, có chủ đích) | Có (subagent executor, ≤3 concurrent) | Có (delegate, ≤3, blocking) | Có (delegate) |
| **Safety model** | **Gate-each-action: Action Gateway = 1 choke-point, policy theo từng action** | Sandbox-first + optional policy middleware + observability | OS-isolation + in-process heuristics (không phải boundary) | **Harness-enforced: exec-approval đa mode + SSRF guard + fs-safe + secret gateway** |
| Hard-deny red line | **✅ Lớp A hard-coded, không bao giờ tới LLM** | ⚠️ Không có blocklist mặc định; allowlist qua config | ⚠️ 12 hardline pattern (rm /, mkfs…) + 47 denylist regex | ✅ `SafeBinProfile` per-binary policy + `policyBlocked` + chặn wrapper-chain (sh -c) |
| Human-in-the-loop | **✅ Lớp B queue + approve, execute thật** | ⚠️ Clarification interrupt (hỏi lại), không phải approval-to-execute | ⚠️ Approval gate (configurable, không bắt buộc) | ✅ `ExecMode: deny\|allowlist\|ask\|auto\|full` + allowlist bền (`exec-approvals.json`) |
| Audit log | **✅ JSONL append-only + redact secret** | ✅ RunEventStore (SQL) | ❌ Không audit; lưu full transcript không redact | ✅ approval/exec runtime ghi state; command-secret gateway redact |
| Budget cap | **✅ $50/tháng hard-stop** | ⚠️ Token usage track, không hard cap | ⚠️ Per-turn iteration budget | (chưa khảo sát rõ) |
| Dedup / idempotency | **✅ reserve-before-execute (SQLite)** | ❌ (dựa checkpointer retry) | ❌ | (chưa khảo sát rõ) |
| Network/FS guard | ❌ không (phạm vi hẹp, không cần) | ⚠️ sandbox FS | ⚠️ OS sandbox | ✅ `fetchWithSsrFGuard` (SSRF) + `@openclaw/fs-safe` (symlink/traversal/owner) |
| Sandbox | **❌ không** (đánh đổi có chủ đích) | ✅ per-thread FS + Docker option | ✅ OS-level (container/VM) là boundary chính | ⚠️ `openshell` ext + fs-safe (in-process safety, không phải full sandbox) |
| Checkpointer | SQLite (state chỉ primitive) | SQLite→Postgres, per-thread | git-style snapshot (không resume giữa turn) | `.jsonl` session + auto-compact |

**Một câu:** Repo này là **MVP nhỏ nhất** nhưng đặt "mọi mutation qua 1 cổng policy-gated với red line
hard-coded trước LLM" làm **trục kiến trúc trung tâm**. Đáng chú ý: **OpenClaw cũng có safety
harness-enforced rất mạnh** (exec-approval đa mode, SSRF/fs guard) — thậm chí *tinh vi hơn repo này ở mặt
shell/exec* — nhưng nó gate ở tầng **exec/command/network**, không phải một "Action Gateway" hợp nhất cho
*mọi* mutation tool. DeerFlow/Hermes thì dựa **sandbox/OS-isolation** là chính. Tức là: repo này không phải
cái duy nhất "có guardrail thật" (nhận định cũ sai); nó là cái đặt guardrail thành **một choke-point hợp
nhất + red-line hard-coded** trong phạm vi action hẹp — gọn nhất, dễ dạy nhất, nhưng cũng hẹp nhất.

---

## 1. Bối cảnh: so cái gì với cái gì (apples vs oranges)

Phải nói thẳng để so cho công bằng: **không cùng hạng cân.**

- **my-project-manager** là agent **dọc** (làm 1 việc: PM reporting), **local-first MVP**, single-agent.
- **DeerFlow / Hermes** là harness **ngang** (general-purpose, chạy mọi loại task), production, multi-agent,
  multi-channel. To gấp ~5–8 lần về code.
- **OpenClaw / Pi.dev** là platform personal-agent đa kênh (Telegram/Slack/Discord/WhatsApp/Feishu… ~30
  channel), production, có plugin SDK. Engine đóng nhưng **cài qua npm → đọc được source/dist** (v2026.6.1).

→ Vì vậy so **năng lực tổng quát** thì repo này *kém xa* (đúng — nó không định làm general). So **mô hình an
toàn cho autonomous write**: repo này có cái DeerFlow/Hermes không nhấn (red-line hard-coded trước LLM +
choke-point hợp nhất), nhưng **OpenClaw cũng có guardrail harness-enforced mạnh** ở mặt exec/network/fs —
không nên nói repo này "độc nhất có guardrail". Phần dưới tách rõ 2 trục.

---

## 2. Trục 1 — Guardrail / Safety / Write-authority (điểm khác biệt cốt lõi)

### 2.1 Bốn triết lý an toàn khác nhau

| Harness | Triết lý an toàn (rút từ code/docs) |
|---|---|
| **my-project-manager** | **Gate-each-action by policy.** Mọi mutation qua `ActionGateway.execute`. Chuỗi: Lớp A hard-deny → Lớp B approve → kill-switch → dry-run → rate-limit → dedup → execute → audit. Red line (data-loss/credential/security) **hard-coded, không tới LLM**. |
| **DeerFlow 2.0** | **Sandbox-first + optional policy + observability.** Cô lập filesystem per-thread (+ Docker option). `GuardrailMiddleware` là *tùy chọn* (bật qua config), provider pluggable (allowlist/denylist). Không có blocklist nguy hiểm mặc định. `SafetyFinishReasonMiddleware` bắt tín hiệu safety của *provider* (content_filter/refusal) rồi chặn tool call. |
| **Hermes-agent** | **OS-isolation là boundary, in-process chỉ là heuristic.** SECURITY.md nói thẳng: chỉ container/VM mới là ranh giới thật; approval pattern + loop-detection KHÔNG phải containment, "một LLM đối kháng hoặc nội dung bị inject có thể vượt qua hết". Có 12 hardline pattern chặn cứng (rm /, mkfs, reboot…) + 47 denylist regex. |
| **OpenClaw / Pi.dev** | **Harness-enforced exec/network/fs guards** (verify từ source `dist/` + `.d.ts`). Exec-approval đa mode `ExecMode: deny\|allowlist\|ask\|auto\|full` + allowlist bền (`~/.openclaw/exec-approvals.json`) + `SafeBinProfile` per-binary (flag được/cấm, số arg) + resolve executable path & chặn wrapper-chain (`policyBlocked`, `blockedWrapper` — chống lách qua `sh -c`). Thêm `fetchWithSsrFGuard` (SSRF) + `@openclaw/fs-safe` (symlink/traversal/owner/outside-workspace) + `command-secret-gateway` (resolve secret cho command, mode enforce/read-only). SOUL.md/persona là *thêm* tầng prompt, KHÔNG phải tầng duy nhất. |

### 2.2 Khác biệt then chốt: choke-point vs middleware vs prompt

- **my-project-manager**: **một** choke-point. Không module nào gọi API write trực tiếp — nếu thấy là bug.
  Code: [`src/actions/action_gateway.py`](../src/actions/action_gateway.py) (`_execute` = cả chuỗi).
- **DeerFlow**: guardrail là **một lớp trong 23 lớp middleware**, và *tùy chọn*. Nếu config không bật
  `guardrails.enabled`, không có policy gating — chỉ còn sandbox + observability. Mạnh ở chỗ pluggable +
  fail-closed; yếu ở chỗ "secure-by-default" không phải mặc định.
- **Hermes**: guardrail là **regex denylist trên shell command** + OS sandbox. Hermes tự thừa nhận denylist
  trên shell (Turing-complete) là "structurally incomplete". Triết lý: đừng tin in-process, hãy cô lập OS.
- **OpenClaw**: **có tầng enforce thật** (không phải prompt). Guardrail là một *cụm* gate ở tầng infra:
  `exec-approvals` (per-command, đa mode) + `fetch-guard` (SSRF) + `fs-safe` + `command-secret-gateway`,
  cộng `account-action-gate` (per-account capability). Khác repo này ở chỗ: nó gate theo **loại tài nguyên**
  (exec / net / fs / secret) thay vì một choke-point hợp nhất cho mọi mutation-tool; SOUL.md là tầng prompt
  *phụ thêm*, không thay thế các gate này.

### 2.3 Cái repo này có mà các harness kia KHÔNG nhấn (hoặc yếu hơn)

1. **Lớp A red-line hard-coded, không bao giờ tới LLM, áp cho MỌI mutation-tool.** DeerFlow không có blocklist
   mặc định; Hermes có hardline nhưng chỉ cho *shell*; **OpenClaw có policy enforce mạnh nhưng tập trung ở
   exec/net/fs** (không phải một red-line thống nhất cho mọi tool MCP/API). → Repo này độc đáo ở chỗ "xóa
   branch / lộ token / public hóa repo" bị chặn ở *kiến trúc, trước LLM*, qua **cùng một** cổng cho mọi loại
   mutation — không phải ở chỗ "có guardrail" (cả OpenClaw cũng có).
2. **Allowlist-default-deny cho MỌI tool** (không chỉ shell/exec). Chuyển từ denylist sau khi review đối kháng
   tìm bypass thật (xem journal Phase 0). DeerFlow allowlist là opt-in; Hermes là denylist; OpenClaw allowlist
   ở tầng exec (`ExecMode=allowlist` + `SafeBinProfile`) — rất mạnh cho shell, nhưng không phủ tool-API chung.
3. **Lớp B approve-to-EXECUTE.** DeerFlow `ClarificationMiddleware` chỉ *hỏi lại rồi END*; Hermes approval
   *configurable, không bắt buộc*; **OpenClaw CÓ approve-to-execute thật** (`ExecMode=ask` + allowlist bền
   `exec-approvals.json` — giống Lớp B của repo này, và phong phú mode hơn). → Đây là chỗ OpenClaw *ngang
   hoặc hơn* repo này, không phải kém. (Nhận định cũ "OpenClaw chỉ draft-prompt" là SAI.)
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
4. **Network/FS guard tinh vi.** OpenClaw có `fetchWithSsrFGuard` (chống agent gọi internal/metadata URL) +
   `@openclaw/fs-safe` (chặn symlink-escape, path-traversal, ghi ngoài workspace, file không owner) — repo
   này **không có** (không cần, vì không exec/fetch tùy ý). Nếu mở scope, đây là thứ phải mượn từ OpenClaw.

### 2.5 Kết luận trục 1

> Về **kiểm soát autonomous write cho một agent dọc, phạm vi hẹp**, mô hình Action Gateway của repo này
> **gọn và tường minh nhất**: nó biến red line thành bất biến *kiến trúc* (hard-coded, trước LLM) qua **một
> choke-point hợp nhất cho mọi mutation-tool** — khác *chính sách tùy chọn* (DeerFlow) và *heuristic shell*
> (Hermes). NHƯNG **không phải "cái duy nhất có guardrail thật"**: OpenClaw có safety harness-enforced *tinh
> vi hơn* ở mặt exec/net/fs (per-binary policy, SSRF guard, fs-safe, approve-to-execute đa mode) — chỉ là nó
> gate theo *loại tài nguyên* thay vì hợp nhất một cổng. (Đây là điểm bản đầu báo cáo nhận định sai.)
>
> Khác biệt thật sự còn lại sau khi đính chính:
> - **Hợp nhất vs phân tán**: repo này = *một* cổng cho mọi mutation (dễ audit "mọi write ở đâu"); OpenClaw =
>   *cụm* gate theo tài nguyên (mạnh hơn cho shell/net/fs, nhưng không có khái niệm "một điểm cho mọi write").
> - **Bề rộng**: repo này hẹp (post Slack/Confluence) nên *không cần* sandbox/SSRF/fs-safe; OpenClaw rộng
>   (shell, fetch, fs) nên *bắt buộc* phải có. DeerFlow/Hermes rộng hơn nữa nên dựa **sandbox/OS-isolation**.
> - Hai câu hỏi khác nhau: *"agent không vượt red line?"* (gateway hợp nhất, repo này) vs *"cô lập agent +
>   gate từng tài nguyên nguy hiểm?"* (OpenClaw/DeerFlow/Hermes). Agent general production cần **cả hai**.

---

## 3. Trục 2 — Kiến trúc agent-core

### 3.1 Orchestration

| | Mô hình | Đánh giá |
|---|---|---|
| **my-project-manager** | LangGraph StateGraph **tường minh**: `perceive→analyze→compose→deliver`, node cố định, không có agentic-loop ẩn. | Mọi bước agent quyết định *nhìn thấy được trong graph*. Dễ test, dễ audit, dễ resume. Đánh đổi: kém linh hoạt cho task mở (agent không "tự nghĩ ra bước"). Hợp với agent dọc, lịch trình. |
| **DeerFlow** | LangGraph + `create_agent` (tool-calling loop) + 23 lớp middleware có thứ tự. | Loop linh hoạt (agent tự chọn tool tới khi xong) + middleware tách concern (sandbox, memory, guardrail, summarize…). Mạnh, nhưng nặng: thứ tự 23 lớp là một API mặt phải hiểu. |
| **Hermes** | ReAct while-loop thuần (không graph). | Đơn giản về cấu trúc, nhưng `conversation_loop.py` ~3,900 dòng — logic dồn vào một loop lớn. Không resume-giữa-turn. |
| **OpenClaw/Pi.dev** | Custom harness (Pi.dev) + plugin/channel-contract SDK; session `.jsonl` auto-compact. | Đa kênh thật (~30 channel ext) qua một channel-contract SDK + plugin SDK có contract-testing → kiến trúc extension hoá rất mạnh. Trục là "harness + plugin", không phải graph tường minh. |

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
   là approval giả. Hermes **và OpenClaw** đều có approval-gate thật (OpenClaw `ExecMode=ask` + allowlist bền
   là tham chiếu tốt cho ai muốn làm phong phú hơn mô hình Lớp B 2-trạng-thái của repo này).

---

## 5. Định vị một dòng

**`my-project-manager`** = *"agent dọc nhỏ nhất với guardrail-write HỢP NHẤT tường minh nhất"*. Nó không cạnh
tranh bề rộng với DeerFlow/Hermes/OpenClaw — nó **chứng minh một luận điểm**: có thể cho LLM full autonomous
write mà vẫn an toàn, **không cần sandbox**, nếu (a) phạm vi action hẹp + allowlist, (b) red line hard-coded
trước LLM, (c) **mọi write qua MỘT cổng có audit**. Điểm khác biệt sau khi đính chính không phải "có guardrail"
(OpenClaw cũng có, còn tinh vi hơn ở exec/net/fs) mà là **sự HỢP NHẤT**: gom mọi mutation về một choke-point
duy nhất với red-line bất biến — gọn nhất, dễ audit "mọi write ở đâu" nhất, dễ dạy nhất. Các harness kia gate
mạnh hơn nhưng *phân tán theo tài nguyên* hoặc *dựa sandbox*. Đó là lý do repo này đáng đọc như tài liệu học
*về một pattern guardrail cụ thể*, dù nhỏ — không phải vì nó "an toàn hơn", mà vì nó "hợp nhất + tường minh hơn".

---

## Unresolved / giới hạn của đánh giá này

1. **OpenClaw đánh giá từ `dist/` đã build + `.d.ts`** (không phải `src/` gốc — npm package chỉ ship
   templates trong `src/`). Đủ để đọc chính xác *cơ chế* (tên symbol, type, mode) nhưng chưa đọc *luồng thực
   thi đầy đủ*; ví dụ budget cap / rate-limit / dedup của OpenClaw chưa khảo sát rõ (đánh dấu "chưa rõ" trong
   bảng, không kết luận là "không có").
2. **Bài học lớn của chính báo cáo này:** bản đầu kết luận OpenClaw "no harness guardrail, persona-prompt only"
   vì tìm source trượt (nó cài qua npm global, không phải `~/workspace`; `find ~` cho `*openclaw*` rỗng do
   tên package không khớp). → *Khi không tìm thấy source, "không có source" KHÔNG đồng nghĩa "không có tính
   năng"* — phải tìm cả npm/pip global, `/opt`, dotdir trước khi kết luận.
3. **Chưa benchmark hiệu năng/độ tin cậy thực tế** giữa 4 — so ở mức kiến trúc + cơ chế, không phải số liệu chạy.
4. **DeerFlow/Hermes/OpenClaw liên tục phát triển** — số liệu (LOC, mode, số middleware) là snapshot lúc khảo sát.
