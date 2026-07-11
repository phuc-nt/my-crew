# Interview Prep — AI Product Owner (Technical Check)

Bạn phỏng vấn vị trí **AI Product PO**. Phần tech-check không đòi bạn code, nhưng đòi bạn
chứng minh: hiểu **concept**, đọc được **system design**, biết **design pattern** ở mức PO —
tức là **nói được "cái gì", "tại sao chọn thế", "đánh đổi ra sao"**, chứ không cần viết hàm.

Tài liệu này lấy chất liệu 100% từ sản phẩm bạn đã build: **my-project-manager** — một agent xây
**trên LangGraph** (thuộc hệ sinh thái LangChain), tự vận hành công việc PM/Scrum Master cho team,
có toàn quyền ghi (post Slack, tạo Confluence page) nhưng an toàn nhờ một cổng guardrail duy nhất.

> **Đính chính stack (nói cho đúng ngay từ đầu):** sản phẩm build **trên LangGraph**. LangChain
> hiện diện ở vai trò **lớp nền** (`langchain-core` — thứ mà LangGraph bắt buộc dựa vào) cộng **một
> adapter** để nối MCP; phần agent thật sự — đồ thị trạng thái, checkpointer, interrupt — là **LangGraph**.
> Khi kể "build với LangChain" thì không sai (LangGraph nằm trong hệ sinh thái đó), nhưng **nói rõ
> LangGraph** sẽ ăn điểm hơn vì đó là phần khó.

> **Câu chốt để mở đầu mọi câu trả lời:** *"Tôi không xây một con chatbot hỏi-đáp. Tôi xây một
> agent tự chạy theo lịch, tự đọc trạng thái dự án qua nhiều hệ thống, tự suy luận rồi **hành động**
> — và điểm khó không phải là làm nó chạy, mà là làm nó **an toàn khi có quyền ghi thật.**"*

---

## 0. Elevator pitch — 30 giây (học thuộc)

> "Tôi build my-project-manager: một **autonomous agent** xây **trên LangGraph (Python)** — trong
> hệ sinh thái LangChain. Nó thay
> con người làm phần việc lặp lại của PM — đọc Jira / GitHub / Confluence / Slack, suy luận về rủi
> ro dự án, rồi tự viết report, cảnh báo blocker, theo dõi OKR. Nó **không phải chatbot** — nó chạy
> theo lịch và **tự hành động**. Cái đáng giá nhất về mặt kỹ thuật là: agent có **toàn quyền ghi**
> nhưng mọi thao tác ghi đều đi qua **một cổng duy nhất — Action Gateway** — nơi có **red line
> cứng mà LLM không bao giờ vượt được**, kể cả khi model 'muốn'. Triết lý một dòng:
> ***autonomous về tốc độ, không bao giờ autonomous về trách nhiệm.***"

Vì sao câu này ăn điểm: nó thể hiện bạn tách được **"agent" vs "chatbot"**, nắm được **rủi ro của
quyền ghi tự động**, và có một **nguyên tắc sản phẩm** rõ ràng — đúng ngôn ngữ của PO, không phải dev.

---

## 1. Trọng tâm: "Vì sao tự build agent từ đầu trên LangGraph?"

Đây gần như chắc chắn là câu họ hỏi. Chuẩn bị kỹ nhất phần này.

### 1.1 Phân biệt LangChain vs LangGraph (đừng lẫn — họ sẽ để ý)

| | LangChain | LangGraph |
|---|---|---|
| Là gì | Bộ thư viện "chất kết dính": chuẩn hoá cách gọi LLM, tool, prompt, memory | Framework xây agent dạng **đồ thị trạng thái** (state machine) trên nền LangChain |
| Dùng cho | Chain tuyến tính đơn giản (prompt → LLM → output) | Luồng có nhánh, vòng lặp, nhiều bước, cần checkpoint & khôi phục |
| Sản phẩm này dùng | Chỉ ở **lớp nền** (`langchain-core`, mà LangGraph dựa vào) + **1 adapter** (`langchain-mcp-adapters` để nối MCP server) | **Xương sống**: graph `perceive → analyze → compose → deliver`, checkpointer, interrupt |

**Sản phẩm build trên gì — nói dứt khoát:** *"Trên **LangGraph**. LangChain có mặt như lớp nền
(`langchain-core`) mà LangGraph bắt buộc dựa vào, cộng một adapter nối MCP. Phần tôi thiết kế và
điều phối — agent thật sự — là LangGraph."*

**Bằng chứng nếu bị hỏi cụ thể** (biết để tự tin, không cần đọc vanh vách): dependency chính là
`langgraph` + `langgraph-checkpoint-sqlite/postgres`; trong code, import từ `langgraph.*` áp đảo
(graph, checkpoint, store, types), còn `langchain_*` chỉ xuất hiện đúng ở adapter MCP.

**Câu nói gọn:** *"LangChain là lớp chuẩn hoá để nói chuyện với model và tool. LangGraph là lớp
điều phối — tôi mô hình hoá agent thành một đồ thị các bước rõ ràng, thay vì để model tự do lặp
trong một vòng lặp mờ."*

### 1.2 Vì sao "từ đầu", không dùng no-code / assistant có sẵn?

Trả lời theo **trade-off**, không theo "vì tôi thích":

1. **Cần controllability, không cần magic.** Agent tự chạy có quyền ghi thật. Tôi cần biết
   **chính xác** nó sẽ làm bước nào, khi nào dừng để hỏi người. Một đồ thị tường minh
   (`perceive → analyze → compose → deliver`) cho tôi điều đó; một "agent loop" ẩn thì không.
   → *Đây là điểm PO ăn tiền: chọn kiến trúc theo yêu cầu **an toàn & giải trình**, không theo độ "xịn".*

2. **Cần chèn được guardrail vào đúng chỗ.** Vì tôi sở hữu luồng, tôi ép **mọi mutation** đi qua
   một choke point (Action Gateway). Nền tảng đóng gói sẵn thường không cho bạn đặt một
   "red line cứng" bên dưới quyết định của model.

3. **Cần portable & rẻ.** Tôi tách **agent core** khỏi **entrypoint** (CLI / cron / web / Telegram).
   Core không biết nó bị gọi từ đâu → thêm giao diện mới là *cộng thêm*, không phải sửa lõi.

4. **Cần learning + ownership.** Đây cũng là sản phẩm để hiểu sâu cách một harness agent thật vận
   hành — thứ mà dùng SaaS đóng hộp sẽ không học được.

**Chốt:** *"Tự build trên LangGraph không phải vì thích khó, mà vì ba thứ tôi coi là bắt buộc —
kiểm soát luồng, chèn guardrail cứng, và portable — đều đòi tôi sở hữu lớp điều phối. LangGraph cho
tôi đúng lớp đó (đồ thị tường minh + checkpointer + interrupt) mà không phải tự viết lại từ số 0."*

### 1.3 Nếu bị vặn "sao không chờ frameworks mới / dùng thẳng API model?"

*"Gọi thẳng API là được cho một prompt đơn. Nhưng ngay khi có **nhiều bước + trạng thái + cần
dừng-hỏi-người giữa chừng + khôi phục sau crash**, bạn sẽ tự viết lại đúng những gì LangGraph
đã cho: checkpointer, interrupt, state schema. Tôi chọn không phát minh lại."*

---

## 2. Concept nền — thuật ngữ phải nói trôi chảy

Học để **dùng đúng chỗ**, không cần định nghĩa sách vở.

| Thuật ngữ | Nói thế nào ở mức PO |
|---|---|
| **Agent vs Chatbot** | Chatbot phản hồi khi được hỏi. Agent **tự khởi động, tự quyết chuỗi hành động, tự thực thi** để đạt mục tiêu. Sản phẩm của tôi chạy theo cron, không cần ai hỏi. |
| **Harness (bộ cương)** | Toàn bộ môi trường quanh model giữ agent đi đúng: scheduler, memory, tool, **security gate**, guardrail, observability. Model chỉ là một mảnh; harness mới là sản phẩm. |
| **Tool calling / function calling** | Model không tự làm được gì ngoài sinh chữ. "Tool" là cách nó gọi ra thế giới thật (đọc Jira, post Slack). Tôi tách **read tools** và **write actions** thành hai lớp khác nhau. |
| **MCP (Model Context Protocol)** | Chuẩn mở để agent nói chuyện với hệ thống ngoài qua các "MCP server". Tôi có 3 server (Jira/Confluence/Slack) chạy như tiến trình con. Lợi ích: **đổi backend không đụng agent core.** |
| **RAG** | (Nếu hỏi) Retrieval-Augmented Generation: nạp dữ liệu thật vào ngữ cảnh trước khi model trả lời, để nó bám sự thật thay vì bịa. Sản phẩm này "retrieval" bằng cách đọc live từ Jira/Confluence rồi mới compose report. |
| **Human-in-the-loop (HITL)** | Với hành động rủi ro (đóng PR, đổi người phụ trách, gửi ra ngoài công ty), agent **dừng lại xếp hàng chờ người duyệt** rồi mới chạy. |
| **Idempotency (bất biến khi lặp)** | Chạy lại report 2 lần **không được** double-post. Tôi "đặt chỗ trước khi thực thi" (reserve-before-execute) + dedup bền. |
| **Observability** | Nhìn được agent đã làm gì: **audit log không sửa được** (append-only, che secret), run-events, tracing tuỳ chọn, replay lại một lần chạy. |
| **Checkpointer** | Trạng thái mỗi bước được lưu (SQLite/Postgres) → crash giữa chừng vẫn khôi phục, và **dừng-hỏi-người** được vì trạng thái đã persist. |

---

## 3. Đọc được System Design — sơ đồ trong đầu

### 3.1 Luồng agent (nói được không cần nhìn)

```
perceive  →  analyze  →  compose  →  deliver
(đọc Jira/    (suy luận    (viết      (post Slack /
 GitHub/      rủi ro,      report)    tạo Confluence —
 Confluence)  OKR...)                  QUA Action Gateway)
```

- **Đồ thị tường minh, không phải vòng lặp ẩn** — mỗi bước rõ ràng, kiểm thử được, giải trình được.
- **State chỉ chứa primitive** + được checkpoint → khôi phục & interrupt được.
- **Tools = lớp đọc. Actions = lớp ghi.** Hai lớp tách biệt là quyết định thiết kế cốt lõi.

### 3.2 Action Gateway — "viên ngọc" của sản phẩm (phải kể vanh vách)

Mọi lệnh ghi đi qua **một** choke point, áp dụng **theo thứ tự**:

```
request → [Lớp A: hard-deny (red line)] → [Lớp B: cần người duyệt? → xếp hàng]
        → [kill-switch] → [dry-run?] → [rate-limit]
        → [dedup (đặt-chỗ-trước-khi-chạy)]
        → [thực thi] → [ghi audit log không sửa được] → trả kết quả
```

- **Lớp A — red line cứng, hard-code, LLM không bao giờ chạm tới:** mất dữ liệu vĩnh viễn, lộ
  credential, sự cố bảo mật. **Bị chặn tại cổng — không phải là quyết định của model.**
- **Lớp B — human-in-the-loop:** merge/close PR, đổi người phụ trách thật, post ra kênh
  **stakeholder ngoài công ty**. Xếp hàng, người duyệt xong mới chạy.
- **Allowlist, không phải denylist:** tool lạ **mặc định bị chặn**. (Đổi sang allowlist sau khi
  review đối kháng tìm ra đường lách của denylist — xem mục 4.)

**Một câu chốt vàng cho interviewer:** *"Guardrail không phải add-on. Nó là **bất biến kiến trúc**
— mọi write đều phải đi qua, không có đường vòng. Tôi có thể mở rộng thoải mái phần đọc/suy luận,
nhưng lớp trách nhiệm thì bất khả xâm phạm."*

### 3.3 Design pattern nhận diện được (gọi tên khi phù hợp)

| Pattern | Ở đâu trong sản phẩm | Vì sao |
|---|---|---|
| **Gateway / choke point** | Action Gateway | Một cửa duy nhất để áp mọi policy ghi |
| **Allowlist (default-deny)** | Hard-block Lớp A | An toàn hơn denylist: cái gì chưa cho phép = cấm |
| **State machine** | Đồ thị LangGraph | Luồng tường minh, kiểm thử & khôi phục được |
| **Adapter** | MCP servers + `gh` CLI | Đổi backend không đụng core; nối hệ thống ngoài qua chuẩn |
| **Plugin / domain pack** | "Thả một folder = thêm domain" (chứng minh bằng HR pack) | Mở rộng không sửa lõi (Open/Closed) |
| **Circuit breaker / kill-switch** | Kill-switch + budget cap $50/tháng | Dừng khẩn cấp, chặn chi phí vượt ngưỡng |
| **Idempotency key** | Reserve-before-execute + dedup | Chạy lại an toàn, không double-post |
| **Separation of concerns** | agent core ⟂ entrypoint (CLI/cron/web/Telegram) | Thêm giao diện là cộng thêm, không sửa lõi |
| **Audit log (append-only)** | Immutable log, che secret | Giải trình & không thể bị viết đè |

### 3.4 Bề rộng năng lực đã build — nói được sản phẩm KHÔNG chỉ là "một con agent"

Đây là phần thiếu nếu chỉ kể guardrail. Sản phẩm đi từ **1 agent PM** thành **một "công ty nhân
sự ảo" do CEO vận hành** qua ~11 vòng lặp (v1→v11). Không cần thuộc số milestone — nhớ **6 nhóm
năng lực** và mỗi nhóm giải quyết *nhu cầu gì*:

| Nhóm năng lực | Đã build gì | Vì sao đáng giá (góc PO) |
|---|---|---|
| **1. Multi-agent platform** | N agent / N project **cô lập** nhau, chạy qua CLI + worker + **scheduler** (cron); một agent **admin** "trông" cả đàn (read-only) | Từ tool cá nhân → nền tảng vận hành nhiều agent. Cô lập = lỗi/agent này không lây sang agent khác |
| **2. Domain packs (mở rộng không sửa lõi)** | Thêm một *lĩnh vực* = **thả một folder** (pack), zero core edit. Chứng minh bằng **HR pack** (đọc Google Sheets) bên cạnh pack PM | Đây là **Open/Closed nguyên tắc thành sản phẩm**: bán thêm domain mà không đụng code lõi → mở rộng thị trường rẻ |
| **3. Memory 4 tầng** | working (trong 1 lần chạy) · internal (giữa các bước) · **cross-agent** (agent anh-em chia sẻ fact, chỉ nội bộ) · long-term (Postgres Store, opt-in) | Agent "nhớ" & "học lẫn nhau" nhưng **không rò dữ liệu ra ngoài** — memory cũng có ranh giới an toàn |
| **4. Human interface đa kênh** | Web SPA (React, low/high-tech dual-mode, light/dark, tiếng Việt) · **Telegram**: mỗi nhân sự ảo có bot riêng, CEO **chat-ops** (giao việc & duyệt Lớp B ngay trong chat) | Người không-kỹ-thuật (CEO) vận hành 100% qua web/chat. Duyệt hành động rủi ro **trên điện thoại** |
| **5. Observability & vận hành tin cậy** | Audit log bất biến · run-events · **replay** một lần chạy (có guard chặn replay không an toàn) · LangSmith tracing (opt-in) · **agent chết ngầm → ping CEO qua Telegram** · multi-project rollup | Không chỉ "chạy được" mà **biết nó đang làm gì & khi nào hỏng** — điều kiện để giao quyền tự động |
| **6. Trust ladder (giao quyền có kiểm soát)** | CEO **bật tay** auto-approve cho Lớp B với **hạn mức/ngày**; Lớp A / allowlist / kill-switch **luôn kiểm trước** | Sản phẩm hoá đúng bài toán PO: *cân bằng tự động hoá vs kiểm soát* — tin dần theo thời gian, không tin mù |

**Câu tổng để nói gọn cả bảng:** *"Nó không dừng ở một agent viết report. Nó là một **nền tảng
vận hành nhiều agent** cho người không-kỹ-thuật: mở rộng lĩnh vực bằng cách thả folder, có bộ nhớ
nhiều tầng, quan sát được từng hành động, và một **thang tin cậy** để CEO giao quyền tự động dần —
nhưng red line an toàn thì không bao giờ đánh đổi."*

**Về mặt kỹ thuật nền, đã đụng tới (biết để không bị hớ):** FastAPI + **SSE streaming** (đẩy tiến
trình chạy real-time về web), **Postgres checkpointer/Store** (opt-in, thay SQLite khi cần bền &
chia sẻ), **MCP suite** 3 server tự đóng gói + publish npm (tối ưu session-reuse, cache, health
probe — xem mục 4), và **installer một lệnh** + system-health panel cho onboarding trọn gói.

---

## 4. Kể chuyện "bug thật + bài học" — phần ghi điểm mạnh nhất

Interviewer thích **quyết định dưới áp lực**, không thích slide hoàn hảo. Bạn có sẵn 3 câu chuyện thật:

1. **Denylist → Allowlist.** Review đối kháng tìm ra 2 đường lách của cách "cấm theo danh sách"
   (secret lọt vào audit log, `gh api` ghi ngầm qua verb dính liền). **Bài học:** với hành động
   không thể hoàn tác, phải **default-deny** — cái gì chưa được phép rõ ràng thì cấm. → Đây là câu
   chuyện "an toàn > tiện" kinh điển, kể được trong 60 giây.

2. **Privacy leak qua artifact liên kết.** Một đường dẫn tưởng vô hại lại kéo theo dữ liệu nhạy
   cảm. **Bài học:** red line phải tính cả **rủi ro gián tiếp**, không chỉ lệnh trực tiếp.

3. **Tối ưu vận hành (v11).** Ban đầu mỗi lần gọi tool là spawn một tiến trình rồi tắt → chậm.
   Chuyển sang **tái dùng phiên** (session pool): weekly report từ 5 lần spawn còn 2 (**−43%**),
   Slack cache cold 363ms → warm 2ms. **Bài học PO:** đo được cái đau vận hành thật rồi mới tối ưu,
   và tối ưu ở **tầng transport** để **không đụng vào guardrail** (bất biến giữ nguyên).

**Mẫu kể (STAR rút gọn):** *Tình huống → Tôi/team làm gì → Kết quả đo được → Bài học.*

---

## 5. Câu hỏi có thể bị hỏi + gợi ý trả lời

**"Agent khác chatbot chỗ nào?"**
→ Chatbot bị động (chờ hỏi). Agent chủ động: tự khởi động theo lịch, tự quyết chuỗi bước, tự thực
thi để đạt mục tiêu. Sản phẩm tôi chạy cron, không ai phải hỏi nó.

**"Làm sao ngăn agent làm bậy khi nó có quyền ghi?"**
→ Kể Action Gateway: một cổng duy nhất, Lớp A red line cứng LLM không chạm tới, Lớp B con người
duyệt, allowlist default-deny, audit log không sửa được. "Autonomous về tốc độ, không về trách nhiệm."

**"Nếu model hallucinate / trả sai thì sao?"**
→ Hai lớp phòng: (1) đọc **live data thật** từ Jira/Confluence rồi mới compose (bám sự thật, không
bịa); (2) hành động rủi ro **không tự chạy** — Lớp A chặn cứng, Lớp B chờ người. Sai của model
không biến thành hậu quả không hoàn tác.

**"Chi phí LLM kiểm soát sao?"**
→ Budget cap $50/tháng có **hard-stop**; kill-switch; DRY_RUN mặc định ở dev (log ra chứ không
thực thi). PO phải nghĩ tới cost & blast-radius, không chỉ tính năng.

**"Chọn model thế nào?"**
→ Có **provider layer + fallback chain** — model chính lỗi thì tụt xuống model dự phòng. Không
khoá cứng một nhà cung cấp; chọn theo tác vụ và ngân sách.

**"Đo thành công của agent bằng gì?"** *(câu PO thuần)*
→ Không phải "model điểm cao". Mà: report có đúng & kịp không, agent có tự chạy ổn định không
(observability: có agent nào chết ngầm?), **tỉ lệ hành động phải chờ người duyệt** (thấp = agent
đáng tin dần), số lần suýt vượt red line (phải = 0), chi phí/tháng trong hạn mức.

**"Scale ra sao?"**
→ Từ 1 agent PM thành "công ty nhân sự ảo": N agent / N project cô lập nhau, một agent admin
"trông" cả đàn, mỗi nhân sự ảo có Telegram riêng, CEO giao việc & duyệt qua chat. Mở rộng bằng
**domain pack thả-vào-folder**, không sửa lõi.

**"Thêm một lĩnh vực mới (vd Sales, HR) tốn bao nhiêu?"** *(câu về khả năng mở rộng sản phẩm)*
→ Rẻ — vì kiến trúc **domain pack**: một lĩnh vực mới là **một folder thả vào**, không sửa code
lõi (Open/Closed). Tôi đã chứng minh bằng HR pack (đọc Google Sheets) chạy song song pack PM. Về
mặt sản phẩm: mở rộng thị trường mà không tăng rủi ro hồi quy lên lõi.

**"Agent có 'nhớ' không? Nhớ thì có rò dữ liệu không?"**
→ Có **memory 4 tầng** (trong-một-lần-chạy / giữa-các-bước / **chia sẻ giữa agent anh-em** /
long-term Postgres opt-in). Nhưng chia sẻ chỉ **nội bộ** — dữ liệu không rò ra ngoài công ty. Memory
cũng nằm trong ranh giới an toàn, không phải "nhớ hết mọi thứ mọi nơi".

**"Làm sao để người dùng dần tin và giao thêm quyền cho agent?"** *(câu PO thuần về automation-vs-control)*
→ **Trust ladder**: mặc định mọi hành động rủi ro (Lớp B) chờ người duyệt. CEO có thể **bật tay**
auto-approve cho Lớp B với **hạn mức mỗi ngày** — tin dần theo thời gian. Nhưng Lớp A / allowlist /
kill-switch **luôn kiểm trước**; quyền tự động **không bao giờ tự kiếm được**, luôn do người cấp.

**"Nếu làm lại, đổi gì?"** *(bẫy khiêm tốn — phải có sẵn 1 câu)*
→ Đưa **allowlist ngay từ đầu** thay vì bắt đầu bằng denylist rồi mới sửa; và tách read/write layer
sớm hơn nữa. Cả hai đều là bài học từ review đối kháng.

---

## 6. Bẫy & mẹo giữ nhịp

- **KHÔNG** nhận vơ mình code từng dòng — bạn là **PO**. Nói "tôi thiết kế luồng, quyết trade-off,
  và review; phần triển khai sâu do agent/dev làm dưới sự điều phối của tôi." Đúng vai, không mất điểm.
- **Đừng lẫn LangChain và LangGraph.** Xem lại mục 1.1.
- **Luôn kèm trade-off.** Mỗi lựa chọn kỹ thuật phải kèm "được gì / mất gì", đó là chất PO.
- Nếu bị hỏi thứ không biết: *"Ở mức PO tôi nắm concept và đánh đổi ở đây là X; chi tiết triển khai
  tôi sẽ kéo dev vào để chốt."* — thành thật, đúng vai, không bịa.
- **Gắn mọi câu về lại sản phẩm thật.** Bạn có lợi thế cực lớn: không nói lý thuyết suông, mà nói
  "trong sản phẩm tôi build, chỗ này tôi đã quyết thế này vì...". Tận dụng tối đa.

---

## 7. Nếu chỉ kịp học 6 điều trước khi vào phòng

1. **Agent ≠ chatbot** — chủ động, tự chạy theo lịch, tự hành động.
2. **Sản phẩm build trên LangGraph** (LangChain chỉ là lớp nền + 1 adapter MCP). LangChain =
   chuẩn hoá gọi model/tool; **LangGraph = điều phối luồng dạng đồ thị**. Tôi chọn LangGraph để
   **kiểm soát luồng + chèn guardrail cứng + portable.**
3. **Action Gateway**: một cổng, Lớp A red-line cứng (LLM không chạm), Lớp B người duyệt,
   allowlist default-deny, audit log bất biến. → *Autonomous về tốc độ, không về trách nhiệm.*
4. **Không chỉ 1 agent — là một NỀN TẢNG:** multi-agent cô lập + scheduler · domain pack thả-folder ·
   memory 4 tầng · observability + replay · Telegram chat-ops · trust ladder. (Bảng mục 3.4.)
5. **Pattern gọi tên được:** gateway, allowlist/default-deny, state machine, adapter (MCP),
   plugin (domain pack), circuit breaker (kill-switch/budget), idempotency.
6. **Một câu chuyện bug thật:** denylist→allowlist sau review đối kháng — an toàn > tiện, với
   hành động không hoàn tác thì mặc định phải cấm.

---

## Câu hỏi còn mở (tự chốt trước khi phỏng vấn)

- JD cụ thể có nhấn mạnh mảng nào (LLMOps? evaluation? prompt/RAG? product metrics?) → soi lại JD
  để dồn thời gian ôn đúng chỗ.
- Công ty phỏng vấn có sản phẩm AI cụ thể không → chuẩn bị 1–2 câu liên hệ sản phẩm của họ với
  bài học từ my-project-manager (nhất là phần guardrail — hầu như team AI nào cũng đang đau chỗ này).
