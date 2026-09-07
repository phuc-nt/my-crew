# my-crew so với các agent harness đã biết (2026-09, tại 0.18.0)

> Nguồn: kiến thức về các harness tới giữa 2026 + tài liệu nghiên cứu trong repo
> (`deerflow-2-architecture-study.md`, `openclaw-hermes-tools-inventory-for-mycrew.md`,
> `harness-enhancement-suggestions-v37.md`, vòng "mượn OpenHuman" 0.16.0). KHÔNG tra lại
> web lúc viết — số phiên bản của họ có thể đã đổi; so sánh trên trục kiến trúc, là thứ ít đổi.
> Mục đích: biết my-crew đứng đâu, cái gì là moat, cái gì đang thiếu — không phải bảng xếp hạng.

## 1. Tọa độ: my-crew là gì, không là gì

my-crew = **harness vận hành một công ty một-người**: đội agent có vai, chạy theo lịch + theo
lệnh qua Telegram/web, tự phân rã việc, làm, soát chéo, và **ghi ra hệ thống thật** (Jira,
GitHub, Confluence, Slack, Gmail, Calendar) qua một cổng duy nhất. Không phải thư viện để dev
lắp agent (CrewAI/LangGraph/ADK), không phải coding agent (Claude Code/OpenHands), không phải
chatbot có tool. Nó gần nhất với nhóm "personal-ops harness" (OpenClaw/Hermes, Manus-kiểu) nhưng
đi theo hướng **đội có ranh giới** thay vì một agent vạn năng.

## 2. Bảng trục

| Trục | my-crew 0.18.0 | CrewAI / AutoGen(AG2) / MetaGPT | LangGraph / OpenAI Agents SDK / Google ADK | Claude Agent SDK · Claude Code / OpenHands | OpenClaw · Hermes / DeerFlow |
|---|---|---|---|---|---|
| Đơn vị điều phối | Task DAG ≤7 bước, hash-bind chống sửa; **phễu 6 lớp** mặc định 1 agent (sprint), chỉ lên đội khi có *cấu trúc* (do + soát chéo độc lập, chuỗi quyền) | Crew/role → sequential/hierarchical; AutoGen group-chat; MetaGPT SOP theo vai "công ty phần mềm" | Graph/state machine, handoff giữa agent; dev tự viết luồng | Một agent + subagent, vòng tool-use, chấm dứt do model | Một agent chính + skill/tool; DeerFlow: planner→researcher→reporter |
| Ai quyết "đội hay một người" | **Code** (tín hiệu đo được: >1200 ký tự, >10 thực thể, ≥3 đầu việc), downgrade sau decompose 0 gọi model, dead-end tự lật; đo 3,6–7× nhanh, 4,1× rẻ, chấm mù 4/5 | Dev khai báo trước | Dev khai báo trước | Model quyết (spawn subagent) | Model/dev |
| An toàn hành động ghi ra ngoài | **Action Gateway** một cửa: Lớp A chặn cứng (mất dữ liệu, lộ bí mật) không toggle; Lớp B autonomous/guarded per-agent; allowlist; kill-switch; audit hash-chain; PII firewall | Không có tầng gateway; tool tự lo; human-in-loop theo turn | Guardrail hook input/output (OpenAI), callback (ADK); không có chính sách ghi-ra-ngoài chuẩn | Permission prompt per-tool, allow/deny list; sandbox (OpenHands Docker) | Hermes có approval hook; OpenClaw sandbox exec; không audit chain |
| Chạy lâu dài, không ai nhìn | Scheduler + cron, heartbeat, dispatch hướng sự kiện 0–8 s, kill-9 resume, retry = attempt mới; **autopilot** AI là người duyệt cuối trừ Lớp A + trần tiền | Không có scheduler nội tại (tự ghép) | LangGraph có checkpoint/durable execution; ADK có session; cần host riêng | Session một lần; Claude Code có background task/cron trong session | OpenClaw có cron/gateway daemon; DeerFlow chạy theo request |
| Trần chi phí là phanh thật | `cost_cap_usd` per-step **mặc định bật** tier tools, halt cả bước đang chạy; per-task cap; per-agent tháng; trần review = 2× bước nội dung | Có max_rpm/token limit, không phanh in-flight | Không có sẵn (tự đo) | Claude Code có max budget flag; OpenHands có budget per task | Không chuẩn |
| Trung thực khi thiếu dữ liệu | Sentinel 3 đường: "web không có" ≠ "không tới được web"; grader neo ngày + đề gốc; thiếu ghi THIẾU; watcher toàn-lỗi không giả "không đổi" | Không có chính sách | Không có chính sách | Model tự xử | DeerFlow có citation, không tách lý do thiếu |
| Trí nhớ | SQLite chung, đội đọc chéo, thư ký read-only, retention 90 ngày; memory extraction là một vai được bench | CrewAI memory (short/long/entity); AutoGen teachability | LangGraph store; ADK memory service | Claude Code: CLAUDE.md + memory dir; OpenHands: condenser | Hermes memory provider; OpenClaw workspace file |
| Đo lường release | Bench 8 mode: routing/release (free, diff 2 báo cáo, từ chối lệch format), tasks (từ store thật), judge mù, reliability k=5, journey, **roles** (7 vai × prompt+parser thật, Wilson, ghi upstream); gate live 66 case; evidence file mỗi bản | Thường không có; benchmark ngoài | LangSmith/OpenAI evals: trace + dataset, tự viết grader | SWE-bench kiểu (OpenHands); Claude Code eval nội bộ | Không |
| Chính sách model | 3 tầng fleet → agent → vai (`role_models`), **suy nghĩ theo vai** (`role_reasoning`), `max_tokens` cứng, guard trả rỗng/đốt trần, `provider` ghi trên mọi lời gọi, `provider_ignore` | Per-agent LLM; không có chính sách reasoning theo vai | Per-agent/per-node; reasoning param tự truyền | Một model, effort flag | Hermes multi-provider routing (my-crew chưa có — ghi ở đề xuất v37 #3) |
| Kênh với người | Telegram thư ký + web cockpit 3D + SSE; một câu tiếng Việt → DAG | CLI/Python API; UI ngoài | API; ADK có web dev UI | Terminal/IDE; OpenHands web | OpenClaw đa kênh (Telegram, WhatsApp, Discord…) — rộng hơn my-crew |
| Cộng đồng / mở rộng | MCP (Jira/Confluence/Slack), domain pack, staff template, skill dir; đề xuất OSV scan khi cài pack (chưa làm) | Plugin/tool ecosystem lớn (CrewAI tools, AutoGen ext) | Lớn nhất (LangChain tools, OpenAI/ADK tools, MCP) | MCP + skills, cộng đồng rất lớn | OpenClaw skill registry lớn; Hermes tools |

## 3. Cái my-crew làm mà harness khác không làm (moat thật, có số đo)

1. **Gateway là kiến trúc, không phải prompt**: Lớp A không bao giờ tới model; allowlist sau
   khi adversarial review phá được denylist; audit hash-chain. Harness khác giao việc này cho
   permission prompt (cần người ngồi đó) hoặc hook do dev tự viết.
2. **Router bằng code, không cần đúng, cần lưới**: mặc định một agent, lên đội chỉ khi có
   ranh giới thật; đo được thuế đa-agent và cắt nó (bench 0.17.0: giết fan-out/merge vì thắng
   4/12 với 1,5× chi phí). CrewAI/AutoGen/MetaGPT mặc định *đội*, không đo thuế.
3. **Release được đo theo vai của model**: `roles` bench trả lời "model này giỏi vai nào" bằng
   parser sản xuất, không judge; ghi upstream nên phân biệt được routing episode với hồi quy
   (0.18.0: review 0,82 do 2 upstream, 0 lỗi ở 8 upstream khác). Chưa thấy harness nào công bố
   cổng release dạng này.
4. **Trần tiền là phanh in-flight** + trung thực có sentinel: đo được worker cháy thêm ~$0.05
   sau lệnh huỷ → sửa thành halt thật.
5. **Vận hành không người nhìn** là mặc định: scheduler, heartbeat, autopilot, escalation lên
   manager agent có chốt chống bão — đây là trục các SDK (LangGraph/OpenAI/ADK) cố ý để dev tự
   xây.

## 4. Cái họ có mà my-crew thiếu (đáng vay tiếp)

| Thiếu | Ai làm tốt | Vì sao đáng | Đã ghi ở |
|---|---|---|---|
| Multi-provider routing (không chỉ OpenRouter), fallback theo provider | Hermes, LangGraph (model fallback), Vercel AI Gateway | 0.18.0 cho thấy chất lượng phụ thuộc upstream; `provider_ignore` mới là né, chưa là chọn | v37 đề xuất #3 |
| Durable execution/resume giữa graph | LangGraph checkpoint, Temporal-kiểu | my-crew retry = attempt mới, mất tiền bước đã xong | PDR §6 (chủ ý) |
| Eval dataset + trace UI | LangSmith, OpenAI evals, Braintrust | Bench my-crew là script + JSON, đọc bằng mắt; blind judge vẫn n<3 | releasing §4 |
| Đa kênh rộng | OpenClaw | Chỉ Telegram + web | roadmap Zalo hoãn |
| Skill/pack registry có quét dependency | OpenClaw, Claude skills | Cài pack cộng đồng chưa có OSV scan | v37 #4 |
| Background review dùng toolset chỉ-đọc | Claude Code subagent read-only | Reviewer my-crew là bước graph, không fork sub-run | v37 #5 |
| Sandbox code chuẩn (agent-computer interface) | OpenHands | deep-agent Docker của my-crew network-off, không mount host — an toàn hơn nhưng hẹp hơn | deep-agent-safety-checklist |

## 5. Kết luận một đoạn

my-crew không cạnh tranh với SDK (LangGraph là nền của nó) hay coding agent; nó nằm ở lớp
**"harness vận hành"** cùng OpenClaw/Hermes/DeerFlow, và khác họ ở ba chỗ: cổng hành động là
kiến trúc, đội chỉ được mở khi code thấy ranh giới, và mỗi bản release có bằng chứng đo theo
vai của model. Điểm yếu thật là phụ thuộc một cửa OpenRouter (đã lộ ở 0.18.0), thiếu resume
giữa chừng, và trục chất lượng deliverable chưa đủ mẫu.

## Câu hỏi chưa giải quyết

- Có nên làm multi-provider (chọn upstream theo vai, không chỉ né) trước hay sau blind judge n≥3?
- Durable resume có đáng đánh đổi nguyên tắc "retry = attempt mới" (đơn giản, audit rõ) không?
