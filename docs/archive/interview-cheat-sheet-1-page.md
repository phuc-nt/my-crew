# CHEAT-SHEET 1 TRANG — đọc ngay trước giờ phỏng vấn

> Chi tiết đầy đủ: [interview-prep-ai-product-po.md](interview-prep-ai-product-po.md)

## 🎯 3 CÂU NEO (nói lại nhiều lần)
1. **"Agent, không phải chatbot"** — tự chạy theo lịch, tự hành động.
2. **"Autonomous về tốc độ, KHÔNG bao giờ về trách nhiệm."**
3. **"Guardrail là bất biến kiến trúc, không phải add-on."**

## 🗣️ PITCH 15 GIÂY
> "Agent xây **trên LangGraph** (Python), tự làm việc PM: đọc Jira/GitHub/Confluence/Slack → suy
> luận rủi ro → **tự viết report, cảnh báo, theo dõi OKR**. Có **toàn quyền ghi** nhưng an toàn vì
> mọi write đi qua **một cổng — Action Gateway** — có red line cứng LLM không vượt được."

## ⚙️ STACK — NÓI CHO ĐÚNG
- Build **trên LangGraph** (KHÔNG phải LangChain thuần).
- LangChain = **lớp nền** (`langchain-core`) + **1 adapter** nối MCP. Phần agent thật = **LangGraph**.
- **LangChain** = chuẩn hoá gọi model/tool · **LangGraph** = điều phối luồng dạng **đồ thị trạng thái**.

## 🧩 VÌ SAO TỰ BUILD TRÊN LANGGRAPH (3 lý do — theo trade-off)
1. **Kiểm soát luồng** — đồ thị tường minh, không phải "agent loop" ẩn → giải trình & test được.
2. **Chèn được guardrail cứng** — vì sở hữu luồng, ép mọi write qua 1 choke point.
3. **Portable** — agent core tách khỏi entrypoint (CLI/cron/web/Telegram) → thêm UI = cộng thêm.

## 🔒 ACTION GATEWAY (kể vanh vách)
```
write → [Lớp A red-line CỨNG] → [Lớp B chờ NGƯỜI duyệt] → kill-switch
      → dry-run → rate-limit → dedup → thực thi → audit-log bất biến
```
- **Lớp A** = mất data / lộ credential / bảo mật → chặn tại cổng, **LLM không chạm tới**.
- **Lớp B** = merge PR / đổi người / gửi RA NGOÀI công ty → **người duyệt** mới chạy.
- **Allowlist default-deny** = tool lạ mặc định CẤM.

## 🔤 LUỒNG AGENT
`perceive → analyze → compose → deliver` — đồ thị tường minh, state checkpoint, dừng-hỏi-người được.

## 🏗️ DESIGN PATTERN (gọi tên khi hợp)
Gateway · Allowlist/default-deny · State machine · Adapter (MCP) · Plugin (domain pack) ·
Circuit-breaker (kill-switch + budget $50/th) · Idempotency (dedup) · Audit log append-only.

## 💬 THUẬT NGỮ — 1 dòng mỗi cái
- **Agent vs chatbot**: chủ động tự chạy vs bị động chờ hỏi.
- **Harness**: cả môi trường quanh model (scheduler, memory, security gate, observability).
- **MCP**: chuẩn nối hệ thống ngoài → đổi backend không đụng core.
- **HITL**: hành động rủi ro dừng chờ người duyệt.
- **Idempotency**: chạy lại 2 lần không double-post.
- **Observability**: audit log + run-events + replay → nhìn được agent làm gì.
- **Checkpointer**: lưu state mỗi bước → khôi phục sau crash + interrupt được.

## 🐛 KỂ 1 BUG THẬT (60 giây, kiểu STAR)
**Denylist → Allowlist**: review đối kháng tìm ra 2 đường lách của "cấm theo danh sách" (secret lọt
audit log; `gh api` ghi ngầm). → Đổi sang **default-deny**. **Bài học: với hành động không hoàn tác,
cái gì chưa cho phép rõ ràng thì CẤM.**
*(Dự phòng: session-pool v11 → weekly 5→2 spawn, −43%; tối ưu ở tầng transport, không đụng guardrail.)*

## ❓ Q&A NHANH
- **Model sai/hallucinate?** → đọc live data thật (bám sự thật) + hành động rủi ro không tự chạy (Lớp A chặn / Lớp B chờ người).
- **Kiểm soát cost?** → budget cap $50/th hard-stop + kill-switch + DRY_RUN mặc định ở dev.
- **Đo thành công?** → report đúng+kịp · agent chạy ổn không chết ngầm · tỉ lệ phải-chờ-duyệt giảm dần · lần suýt vượt red-line = 0 · cost trong hạn.
- **Scale?** → 1 PM agent → "công ty nhân sự ảo": N agent/N project cô lập, admin trông cả đàn, domain pack thả-vào-folder.

## ⚠️ ĐỪNG QUÊN
- Mình là **PO**: thiết kế luồng + quyết trade-off + review; KHÔNG nhận vơ code từng dòng.
- Đừng lẫn LangChain ↔ LangGraph.
- Mỗi lựa chọn → kèm **trade-off** (được gì/mất gì).
- Không biết → *"mức PO tôi nắm concept & đánh đổi là X; chi tiết tôi kéo dev vào chốt."*
- **Gắn mọi câu về lại sản phẩm thật đã build.**
