# Project Overview & PDR — my-crew

> Product definition + requirements. Đọc file này TRƯỚC khi plan hay code.
> Cập nhật: 2026-09-03 (0.17.0). Trạng thái: **production-usable, single-user, autonomy-first, live E2E verified — PyPI 0.17.0** (đội chỉ giữ hai dạng có ranh giới thật: do + soát chéo độc lập, chuỗi quyền; mọi việc đội luôn kết thúc bằng kết luận; trần chi phí per-step bật mặc định ở tier tools).
> Liên quan: [system-architecture](system-architecture.md) · [action-gateway-explainer](action-gateway-explainer.md) · [uat-theo-user-story](uat-theo-user-story.md).

## 1. Vấn đề

Một founder/CEO công ty một-người phải tự làm toàn bộ việc "quản lý": theo dõi Jira,
đọc GitHub, cập nhật OKR ở Confluence, viết báo cáo, nhắc nhở, tổng hợp. Việc lặp lại,
tốn thời gian, và không scale khi chỉ có một người.

## 2. Sản phẩm

Một **đội nhân sự ảo AI** do một người điều hành. CEO giao việc bằng ngôn ngữ tự nhiên
(web hoặc Telegram); các agent — mỗi con một vai trò (điều phối / nghiên cứu / nội dung /
phân tích / kiểm định / **thư ký riêng**) — tự phân rã việc, làm, soát chéo nhau, và *tự
hành động* trên hệ thống thật (Jira/GitHub/Confluence/Slack/Gmail/Calendar). Không phải
chatbot hỏi-đáp; là đội tự làm việc theo lịch và theo lệnh.

Từ v57–v66 (arc thư ký), cửa vận hành chính là **chat Telegram với thư ký**: việc cá nhân
(briefing, email, lịch, nhắc đúng giờ) lẫn việc công ty (giao việc đội, chỉnh giữa chừng,
xem kanban + chi phí) đi qua một cửa; **autopilot** cho phép AI là người quyết cuối
(tự xác nhận kế hoạch, tự gỡ kẹt, tự duyệt Lớp B) — Lớp A + trần chi phí vẫn chỉ người
thật đổi được.

Từ v70–v75 (arc tốc độ + coordination chủ động), giá trị đo được bằng số: một đề khảo
sát 5-6 thực thể từ ~40 phút xuống **11–16 phút, $0.02–0.05/việc** (dispatch hướng sự
kiện 0–8s, bước không-tool chạy tier nhẹ, thu thập tách song song + code pre-fetch);
task bế tắc được coordinator **tự thử lại → tự đề xuất KẾ HOẠCH KHÁC → tự chấp nhận/bỏ**
theo thang có trần, mọi nấc audit + báo CEO; chuỗi trung thực giữ tuyệt đối — thiếu dữ
liệu ghi THIẾU kèm đúng lý do ("web không có" khác "không tới được web"), không bịa số.

Từ v76–v79 (arc sprint + phễu định tuyến), đề một-người không còn trả "thuế đa-agent":
**sprint mode** chạy 1 agent duy nhất do code điều nhịp (prefetch → draft → coverage
check → revise ≤2 vòng), là team task suy biến nên thừa kế nguyên bộ review/clarify/
escalate/delivery. **Phễu định tuyến 6 lớp** mặc định sprint, chỉ đẩy team khi có tín
hiệu CẤU TRÚC (>1200 ký tự, >10 thực thể, ≥3 đầu việc); plan suy biến sau decompose
được kéo về sprint; sprint bế tắc tự lật sang team — router không cần đúng, cần lưới.
Đo thật: nhanh hơn **3.6–7×, rẻ hơn 4.1×, chấm mù thắng 4/5 cặp**. Kèm theo: autonomy
band per-agent (trusted/normal/supervised, loop metrics khép kín), trần review tầng
task + phanh in-flight cho trần chi phí, model config 3 tầng, audit hash-chain.

## 3. Nguyên tắc bất khả xâm phạm (v30: autonomy-first)

> **Tự chủ về TỐC ĐỘ (mặc định); duyệt là tùy chọn. Luôn duyệt về an toàn.**

- Agent chạy nhanh, song song, tự phối hợp — **không cần CEO gật đầu từng bước nội bộ**.
- Hành động ghi **RA NGOÀI công ty** (đăng Slack, gửi email, gộp PR) **chạy ngay mặc định** (autonomous mode, tự chủ) → audit ghi rationale "trust_mode=autonomous"; **hoặc chờ CEO duyệt** (guarded mode, opt-in per-agent via `safety.trust_mode: guarded`).
- MỌI hành động đi qua một cửa duy nhất (**Action Gateway**): việc nguy hiểm (mất dữ liệu / lộ bí mật) bị **chặn cứng LUÔN** (Lớp A, không toggle) — LLM không vượt được kể cả khi "muốn".

Xem [action-gateway-explainer.md](action-gateway-explainer.md) cho mô hình đầy đủ (bảng trust modes + 5 bắt-buộc-nói-thẳng).

## 4. Người dùng & phạm vi

- **Người dùng**: CEO/founder không-kỹ-thuật, một người, vận hành qua web (localhost) +
  Telegram. **KHÔNG** phải multi-tenant, không SaaS công khai — single-user, self-hosted
  trên máy cá nhân/server riêng.
- **Trong phạm vi**: giao việc đội, theo dõi realtime, duyệt hành động, báo cáo định kỳ,
  cảnh báo. Xem 22 user story ở [uat-theo-user-story.md](uat-theo-user-story.md).
- **Ngoài phạm vi (cố ý)**: đăng nhập nhiều người, phân quyền RBAC, thanh toán, chạy cloud
  đa-tenant. Bind LAN chỉ cho phép khi bật web-auth (an toàn mặc định localhost).

## 5. Yêu cầu chức năng (tóm tắt — chi tiết ở user stories)

| Nhóm | Yêu cầu |
|------|---------|
| Đội ngũ | Tạo/tắt/xoá agent; đội = mọi agent enabled; registry là user-data (không mất) |
| Giao việc | @PIC / @all / tự-xác-nhận; phân rã ≤7 bước; hash-bind chống tamper; giao/chỉnh/huỷ qua chat thư ký (catalog scope theo domain) |
| Theo dõi | Màn Văn phòng realtime (3D + feed + kết quả) theo từng phòng việc; kanban + chi phí qua chat |
| Tự vận hành | Soát chéo THEO RỦI RO (chỉ bước cuối + ghi-ra-ngoài, task nhỏ waiver); tự cứu lỗi 1 lần; autopilot: tự xác nhận / tự gỡ kẹt **thang 3 nấc (retry → tự đề xuất kế hoạch khác qua flow amend+hash, fail-closed → accept/drop)** / tự duyệt Lớp B, opt-out per-task; scheduler round-robin công bằng; **autonomy band per-agent (v76)** trusted/normal/supervised chỉ đụng cổng review, loop metrics khép kín (siết tự động, nới cần người, cooldown 3 ngày); **trần review tầng task (v78)** = 2× bước nội dung, sàn 5 — chạm trần thì stall + escalate thay vì đốt tiền |
| Định tuyến (v77–78) | Đề một-người → **sprint mode**: 1 agent code-paced (prefetch → draft → coverage check → revise ≤2 vòng), team task suy biến thừa kế review/clarify/escalate/delivery; **phễu 6 lớp** mặc định sprint, tín hiệu cấu trúc (>1200 ký tự / >10 thực thể / ≥3 đầu việc) đẩy team; downgrade sau decompose (0 gọi model thêm); dead-end tự lật team; tiền tố `sprint:`/`team:` override (KHÔNG ép được sprint khi ghi-ra-ngoài/shell/nhiều người/dài hơi); mọi nhánh log `route_json` (chỉ số đo, không lưu đề); **sprint LUÔN mint đúng 1 review ở mọi band** — không có đường zero-eyes |
| Tốc độ (v74–75) | Dispatch hướng sự kiện (poke, gap 0–8s, fallback nhịp 60s); tier theo bước `needs_web` (bước không-tool chạy native, hint sai tự hồi phục); đề ≥4 thực thể ép tách thu thập song song (fail-open); code pre-fetch search cho bước collect (fail-open về tool-loop); cạn loop tổng hợp từ transcript dở |
| Trung thực | Sentinel 3-path: "web không có dữ liệu" ≠ "không truy cập được nguồn" ở mọi tier; watcher toàn-lỗi không đội lốt "không đổi"; grader neo ngày + trần đề gốc CEO; thiếu ghi THIẾU, không bịa |
| Trợ lý cá nhân | Chat DM tức thì; briefing sáng/tuần (thư ký + **pong** — Goodreads/Google Tasks, weekly không lặp briefing); đọc Gmail/Calendar; gửi email; tạo/sửa/xoá lịch; nhắc đúng-giờ về Telegram; đa-lệnh một tin |
| Trí nhớ | Store SQLite bền dùng chung; đội đọc chéo; thư ký chỉ-đọc (`memory_share: read_only`); retention 90 ngày |
| An toàn (v30) | Action Gateway (Lớp A chặn cứng luôn / Lớp B: autonomous chạy ngay vs guarded duyệt per-agent); PII firewall; chat flatten (autonomous mode); shell chỉ trong Docker sandbox (không mount host, network off, fail-closed); audit hash-chain + break-glass env-only (v76) |
| Model (v79) | Cấu hình 3 tầng: fleet → per-agent → per-role (`role_models` trong profile); fleet mặc định `deepseek/deepseek-v4-flash-latest` |
| Báo cáo | daily/weekly/okr/resource + headcount (hr); xuất .xlsx qua email; đa-audience |
| Cảnh báo | agent chết ngầm, bộ điều phối chưa chạy, thiếu web-search key → Telegram/banner |

## 6. Yêu cầu phi chức năng

- **An toàn > tiện lợi**: không có đường tắt nào bỏ qua gateway; secrets chỉ trong `.env`
  (không qua terminal/URL/log); audit log không sửa được.
- **Bền vững khi lỗi**: mọi ghi realtime (office events, heartbeat) fail-degrade, không
  chặn pipeline. Retry = attempt mới (không resume mid-graph).
- **Chi phí có trần**: mỗi việc đội có cap ($2 mặc định); ngân sách LLM per-agent hàng
  tháng; trần là **phanh thật** (v79): chạm trần thì halt cả bước ĐANG chạy — cancel
  không phải phanh (bài học đo được: worker đã spawn cháy thêm ~$0.05 sau lệnh huỷ).
- **Kiểm chứng thật**: mọi tính năng lớn E2E trên browser + LLM + ticker thật, không chỉ
  suite xanh (bài học "suite xanh ≠ chạy được"); thêm harness fullflow in-process
  (intake→decompose→work→review→aggregate với LLM kịch bản, mutation-verified —
  [fullflow-testing-guide](fullflow-testing-guide.md)).

## 7. Bối cảnh kỹ thuật (1 dòng mỗi cái)

- Backend Python 3.12 (uv) · LangGraph agent graphs · FastAPI + SSE · SQLite WAL.
- Frontend React 19 + Vite + react-three-fiber (màn 3D).
- Tích hợp: MCP (Jira/Confluence/Slack) · `gh` CLI · `gws` CLI · OpenRouter (LLM).
- Kiến trúc chi tiết: [system-architecture.md](system-architecture.md).

## 8. Trạng thái & lộ trình

Đã ship tới **v79 = PyPI 0.10.0** (mốc gần: **v62 English identifiers** · **v63 autopilot
+ review theo rủi ro** · **v64–v66 UAT hardening + nhắc đúng-giờ + cross-agent memory** ·
**v67–v69 learned Lớp B rules + heartbeat + approval từ chat** · **v70–v71 personal
assistant pong + quick-build crew** · **v72–v74 tốc độ**: spawn-then-drain, grader neo
ngày, Telegram coordinator-first, tier theo bước, dispatch poke, fan-out ép code ·
**v75 coordination chủ động**: sentinel 3-path, goal-replan ladder, hybrid collect
launcher · **v76 đo lường + guardrail**: audit hash-chain, autonomy band, metrics
honest-data · **v77 sprint mode** code-paced · **v78 phễu định tuyến 6 lớp** + trần
review tầng task · **v79 model 3 tầng + phanh in-flight + release gate 0.10.0**: delta-UAT
sống 4/4 hành vi trên model + Telegram thật), **3266 BE + 282 FE + 8 e2e tests**,
benchmark sprint-vs-team chấm mù 4/5 cặp sprint thắng, CHANGELOG đầy đủ.
Kiến trúc runtime-tier + moat: xem [system-architecture](system-architecture.md) §3.9.
Lộ trình + việc tiếp: [project-roadmap.md](project-roadmap.md).

## Câu hỏi mở

- Định nghĩa "đội office" đã chốt = mọi agent enabled (không lọc domain) — cân nhắc lại
  nếu sau này có agent không nên nhận việc đội.
- Multi-user/hosted chưa trong phạm vi — cần thiết kế lại auth + isolation nếu mở rộng.
