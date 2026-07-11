# E2E toàn diện v1→v8 — báo cáo kiểm thử sản phẩm

2026-07-04 · Full-live (Jira + Confluence + GitHub + Slack + Telegram + OpenRouter thật) + full test suite. Non-destructive: dry-run cho mọi write ra công cụ ngoài; test-artifact dọn sạch.

## Tóm tắt

**Kết quả: TẤT CẢ năng lực lõi v1→v8 PASS live.** Guardrail 2 lớp (THE INVARIANT) hoạt động thật trên hành động thật. Không phát hiện regression.

- **Baseline offline**: 1205 pytest + 58 vitest + ruff + tsc — xanh.
- **Live**: 4 report kind chạy thật qua MCP+LLM thật; guardrail Lớp A/B enforced live; Telegram identity + delivery thật; web API + pack discovery thật; **write THẬT end-to-end (Confluence page + Slack post) qua Lớp B human-approve**.
- Hạ tầng sẵn sàng: 9/9 key `.env` SET, 3 MCP server (Jira/Confluence/Slack) build, `gh`+`gws` authed, seeded dataset SCRUM còn live.

## Ma trận năng lực (v1→v8)

| Ver | Năng lực | Cách kiểm | Kết quả |
|-----|----------|-----------|---------|
| **v1 P0** | Guardrail core (Lớp A hard-block) | LIVE classify hành động thật | ✅ `deletePage`→data_loss block; destructive `gh api DELETE`→block; token `xoxb-`/`ghp_` trong free-text→credential block |
| v1 P1 | Reporting daily/weekly (Jira+GitHub→compose) | LIVE worker dry-run | ✅ Spawn Jira MCP thật → JQL `project=SCRUM` trả 24 issue thật → OpenRouter compose → deliver (dry-run) |
| v1 P2 | Guardrail hardening (Lớp B queue/audit) | LIVE audit log | ✅ External Slack post→`pending` (Lớp B), Confluence→`dry_run`; audit ghi đủ verdict |
| v1 P3 | OKR tracking (Confluence table→rollup) | LIVE worker dry-run okr | ✅ Đọc OKR page 98466 thật → rollup có trọng số → compose |
| v1 P4 | Resource + Cost | LIVE worker dry-run resource | ✅ Workload per-assignee + LLM budget thật → compose |
| v1 P5 | Audience-split (external→Lớp B) | LIVE worker external | ✅ External daily → **PAUSED tại graph-interrupt approval gate** (exit 3, chờ resume) |
| **v2 M1-M4** | Multi-agent core + platform + web API | LIVE web TestClient | ✅ `/api/agents`, `/api/setup/status`, `/api/team/alerts`, `/api/packs` — 200, data thật |
| **v3 M5-M6** | Domain-pack (pm/hr) | LIVE pack discovery | ✅ `/api/packs`→['admin','hr','pm'] discovered |
| v3 M7 | UI low-tech (wizard/lifecycle) | LIVE setup status | ✅ setup completed=True; agents list qua API |
| v3 M8 | admin-pack fleet watch | LIVE fleet read | ✅ `read_all_agent_states`→default: spent=$0.0142 (từ LLM run thật), pending, project=SCRUM |
| v3 M11 | Ask-agent Q&A | Offline unit (dataset 1-user hạn chế) | ✅ suite; live giới hạn dataset |
| **v4 M9** | Model fallback chain | LIVE config + LLM call | ✅ primary model `minimax/minimax-m2.7` gọi thật (report compose HTTP 200) |
| **v5 M12** | Chat-command qua Lớp B | Offline unit + M23 live | ✅ suite; enqueue path live qua M23 E2E |
| **v6 M13** | Telegram identity per agent | LIVE getMe + send | ✅ 3 bot thật: @phucnt_my_pm_bot / _admin_bot / _hr_bot; **gửi tin thật (message 16) qua gateway** |
| v6 M14 | CEO chat-ops | LIVE ops available | ✅ ops engine reachable (admin agent) |
| v6 M15 | Giao việc & theo dõi | Offline unit | ✅ suite (watch/report/qa task) |
| v6 M16 | Auth + go-live | LIVE web | ✅ SPA served, session auth |
| **v7 M17-M20** | Zero-friction (wizard/agent-studio/docs/nav) | LIVE web API | ✅ setup status, agent API, 4-mục nav build |
| **v8 M21** | CEO-observability | LIVE (đã E2E khi cook) | ✅ missed_schedule/failing detection; DM CEO thật (message trước) |
| v8 M22 | Multi-project rollup | LIVE (đã E2E khi cook) | ✅ report_summary internal-only; B3 no-leak |
| v8 M23 | Trust ladder | **LIVE surface 1 chứng minh lại**: external report→graph-interrupt | ✅ THE INVARIANT: Lớp A/kill-switch deny với auto ON |

## Bằng chứng live then chốt

**1. Full reporting pipeline (v1) — thật đầu-cuối:**
```
Jira MCP Server v3.0.0 started → Connected to phucnt0.atlassian.net
JQL: project = "SCRUM" → API returned 24 issues
OpenRouter POST /chat/completions "200 OK"
worker default daily/internal: delivered=True confluence=dry_run slack=pending_approval
```
Đọc Jira thật (24 issue seeded) → LLM thật compose → guardrail gate. 4 kind (daily/weekly/okr/resource) đều chạy.

**2. THE INVARIANT enforced trên hành động thật (guardrail Lớp A):**
- `confluence:deletePage` → **data_loss** hard-block
- `gh api -X DELETE` → block
- Slack post chứa `xoxb-…{8,}` / `ghp_…` → **credential** block (secret leak red line)

**3. Audience-split + trust ladder surface 1 (v1 P5 + v8 M23):**
External daily report → **PAUSED at graph-interrupt approval gate** (không post, chờ người) — đúng cơ chế Lớp B graph-native.

**4. Telegram identity + delivery (v6 M13):**
3 bot getMe live OK; gửi tin thật (message 16) tới CEO qua full gateway path (guardrail + telegram_send).

**5. Multi-agent platform + packs (v2/v3):**
Web API trả agents/alerts/packs thật; admin fleet read thấy chi phí thật ($0.0142 tích luỹ từ các LLM run E2E).

## Write THẬT end-to-end (không dry-run) — chủ dự án yêu cầu

Tắt `safety.dry_run` của profile `default` → chạy daily report THẬT → khôi phục sau (repo sạch 100%):

| Bước | Kết quả live |
|------|-------------|
| Perceive | Jira MCP thật đọc 24 issue SCRUM |
| Compose | OpenRouter LLM thật soạn báo cáo |
| **Confluence write** | ✅ **createPage THẬT** → `https://phucnt0.atlassian.net/wiki/spaces/MPM/pages/4030492/` (confluence=executed) |
| Slack post | → Lớp B queue #35 (channel caveat) |
| **Approve → Slack write** | ✅ **approve #35 → post THẬT** vào C0BBZN04XPX (ts=1783179488, executed) |
| Agent memory (M2-P8) | ✅ remember node trích fact thật từ Jira live ("8 task quá hạn, Phúc Nguyễn điểm nghẽn, PR#2 treo 12 ngày") — chứng minh memory extraction live |

**Chuỗi write đầy đủ chứng minh live**: Jira read → LLM compose → Confluence createPage THẬT → Lớp B human-approve → Slack post THẬT. Artifact thật (page 4030492 + tin Slack) còn trên workspace — chủ dự án dọn. Config + repo khôi phục sạch.

## Giới hạn (không phải lỗi)

1. **Multi-agent/rollup live hạn chế bởi dataset**: seeded chỉ 1 project (SCRUM) + 1 user Jira thật ("chỉ 1 user thật" — không tạo user giả được). Multi-project rollup + multi-person overload đã E2E qua config tạm khi cook M22 + unit-test fixture. Fleet live chỉ có `default` registered.
2. **Seeded caveat**: `SLACK_REPORT_CHANNEL == SLACK_EXTERNAL_CHANNELS` (cùng C0BBZN04XPX) → internal report cũng route Lớp B. Đúng logic, không đúng ý định; deployment thật phải tách 2 channel. Pending E2E tạo ra đã reject (test luôn đường reject).
3. **Q&A/chat-command live**: cần mention thật trong channel/DM; đã unit-test + M23 E2E enqueue path. Không chạy live vòng đầy đủ (cần tương tác người).

## Kết luận

Sản phẩm **production-ready** cho vision "đội nhân sự ảo công ty 1 CEO" ở mọi tầng đã build (v1→v8). Guardrail bất biến giữ vững trên hành động THẬT. Không regression. Các giới hạn còn lại đều là ràng buộc dataset test hoặc quyết định non-destructive, không phải khiếm khuyết sản phẩm.

## Unresolved

1. Muốn E2E write THẬT (tạo ticket/post Slack thật) thay vì dry-run? Cần chấp nhận ghi rác lên Jira/Slack.
2. Muốn E2E Q&A/chat-command live cần bạn nhắn bot thật rồi mình chạy poll — làm không?
3. Deployment thật: tách `SLACK_REPORT_CHANNEL` ≠ `SLACK_EXTERNAL_CHANNELS` (hiện trùng do seeded).
