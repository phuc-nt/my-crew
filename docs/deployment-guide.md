# Deployment & Setup Guide — my-crew

> Cách cài, chạy, cấu hình, backup. As-built v18, mọi lệnh chạy thật. Chi tiết vận hành
> hằng ngày cho người dùng cuối: [huong-dan-su-dung.md](huong-dan-su-dung.md) (tiếng Việt).
> Cập nhật: 2026-07-11.

## 1. Yêu cầu

| Công cụ | Ghi chú |
|---|---|
| Python 3.12+ | qua `uv` (venv pin 3.12); KHÔNG dùng global 3.14+ |
| `uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js + npm | build FE + MCP servers |
| `git` | |
| `gh` (GitHub CLI) | `gh auth login` (bước tương tác, không tự động được) |
| `gws` (tùy chọn) | chỉ cho hr-pack (Google Sheets) |

Tài khoản/token cần (điền trong trình duyệt, KHÔNG qua terminal): OpenRouter (LLM),
Atlassian (Jira+Confluence), Slack (xoxc+xoxd), GitHub (qua `gh`). Tùy chọn: Tavily/Brave
(web-search cho vai trò nghiên cứu), SMTP (email .xlsx), Telegram (điều hành di động).

**3 MCP server** (Jira/Confluence/Slack — Node, stdio; GitHub dùng `gh` CLI). `install.sh`
cài từ npm mặc định; nếu build từ source (`--mcp-dev`) thì clone + `npm install && npm run build`:

- Jira → [github.com/phuc-nt/jira-cloud-mcp-server](https://github.com/phuc-nt/jira-cloud-mcp-server)
- Confluence → [github.com/phuc-nt/confluence-cloud-mcp-server](https://github.com/phuc-nt/confluence-cloud-mcp-server)
- Slack (browser-token) → [github.com/phuc-nt/slack-browser-mcp-server](https://github.com/phuc-nt/slack-browser-mcp-server)

Trỏ agent tới chúng bằng `JIRA_MCP_DIST` / `CONFLUENCE_MCP_DIST` / `SLACK_MCP_DIST` trong
`.env` nếu không nằm ở mặc định `~/workspace/*-mcp-server`.

## 2. Cài một lệnh (production, macOS/launchd)

```bash
git clone <repo> && cd my-crew
./deploy/install.sh
```

7 bước tự động: [1] preflight (báo thiếu tool + lệnh cài, không tự cài) → [2] `uv sync` →
[3] build web SPA → [4] cài 3 MCP server (npm mặc định; `--mcp-dev` để build từ source) →
[5] tạo `.env`/`registry.yaml` (từ example nếu vắng — v18) → [6] cài **launchd services**
(coordinator + web; reload CHỈ khi plist/SPA đổi — không làm chết agent đang chạy) →
[7] health gate (✓/✗ từng phần trước khi mở trình duyệt).

**Chạy lại an toàn**: gọi lại `./deploy/install.sh` sau `git pull` — idempotent, không
khởi động lại nếu không có gì đổi, không rớt phiên đăng nhập web.

## 3. Setup Wizard (điền bí mật)

Lần đầu, trình duyệt tự mở **Setup Wizard**: điền OpenRouter → Atlassian → Slack → GitHub →
(tùy chọn) web-search → đặt mật khẩu dashboard. Mỗi bước có "Kiểm tra kết nối". Bí mật CHỈ
đi qua wizard (ghi `.env`), không qua terminal/URL. Wizard tự khóa sau khi xong.

## 4. Chạy thủ công (dev, không launchd)

```bash
uv sync
cd web && npm install && npm run build && cd ..        # FE (dist đã commit)
PORT=8765 uv run python -c "from src.server.app import main; main()" &   # web
uv run python -m src.runtime.service &                                   # coordinator
# http://127.0.0.1:8765
```

- **Web**: host `BIND_HOST` (mặc định 127.0.0.1), port `PORT` (mặc định 8765). Bind LAN
  bị TỪ CHỐI trừ khi bật web-auth (`WEB_AUTH_PASSWORD_HASH` + `WEB_SESSION_SECRET`).
- **Coordinator daemon**: BẮT BUỘC chạy thì đội mới dispatch việc. Không chạy → màn Văn
  phòng hiện banner đỏ "bộ điều phối chưa chạy".

## 5. Đội mẫu để thử ngay (demo mode)

```bash
scripts/demo-mode.sh on      # công ty mẫu + đội đủ + coordinator demo cùng chạy
scripts/demo-mode.sh off     # trả data thật NGUYÊN VẸN (byte-identical, đã kiểm)
scripts/demo-mode.sh status  # đang ở chế độ nào + service demo + heartbeat
```

Lưu ý: demo REFUSE bật nếu đã có `src.runtime.service` khác chạy (2 ticker tranh store) —
tắt service thật trước.

Preset demo đủ **3 runtime engine** để thử ngay (mỗi nhân sự 1 engine):

| Nhân sự | Engine | Đặc tính |
|---|---|---|
| kiem-dinh | `native` | graph tự build, chặt nhất, 0 tool tự do |
| noi-dung | `create_agent` | tool-calling loop (langchain.agents, v28), read-only + `web.scrape` |
| nghien-cuu | `deep_agent` | shell tự chủ trong **Docker sandbox** cách ly (token-free, no host mount) |

**v28**: tools-tier migrate sang `langchain.agents.create_agent` (community-standard). deep_agent
cần Docker daemon chạy + model tool-calling mạnh (`qwen/qwen3.7-max` đã pin sẵn trong profile
demo — minimax fail deep loop). `uv sync` cài base deps (tất cả 3 engine sẵn sàng; deep extra
`[deep]` chỉ cần nếu cài như devops độc lập).

## 6. Cấu hình

| File | Vai trò | Git |
|---|---|---|
| `.env` | Secrets (token/key) | ignored |
| `registry.yaml` | Đội (agent ids + enabled) — **user-data v18** | ignored (template: `registry.example.yaml`) |
| `company.yaml` | Tên công ty, coordinator, cap chi phí, auto-confirm | ignored |
| `profiles/<id>/` | Hồ sơ agent (profile.yaml + SOUL/PROJECT/MEMORY.md) | ignored (trừ default/templates) |
| `company-docs/` | Tài liệu công ty inject vào agent | ignored |

> **v18**: `registry.yaml` KHÔNG còn trong git. Fresh checkout tự bootstrap từ
> `registry.example.yaml`. Đừng bao giờ `git checkout registry.yaml`.

### 6a. Chọn runtime engine cho một agent (`agent_runtime`)

**Mặc định là `native`** (graph cố định `perceive → analyze → compose → deliver`) — rẻ,
xác định, đúng cho báo cáo template (daily/weekly/okr). **Giữ native cho các agent báo cáo
định kỳ.** Chỉ bật engine khác cho agent cần **suy luận mở** (research, phân tích ad-hoc):

```yaml
# profiles/<id>/profile.yaml

# LLM tự chọn tool trong vòng lặp (read-only toolset: jira/github/confluence/linear +
# web.scrape + academic.search + history.search; bật gws_context để thêm Gmail/Calendar/Drive).
agent_runtime: create_agent
# hoặc chỉnh cap vòng lặp cho task phức tạp:
agent_runtime:
  kind: create_agent
  runtime_loop_limit: 12          # mặc định 8

# Tự chủ cao nhất: agent tự viết shell/python trong Docker sandbox cách ly. Chậm hơn (vài phút),
# cần Docker + model tool-calling mạnh. File agent ghi vào /work được đọc lại kèm kết quả (v41).
agent_runtime:
  kind: deep_agent
  sandbox:
    provider: docker
    lease_seconds: 1800           # tuỳ chọn: cửa sổ sống của container (mặc định 1800, tối đa 3600)
```

- **`create_agent`** — LLM-tự-chọn-tool, read-only (không ghi ra ngoài, mọi write vẫn qua Gateway ở tầng deliver).
- **`deep_agent`** — shell tự chủ trong sandbox; file trong `/work` (tmpfs, không chạm host). Kết quả trả về text; nếu agent ghi report ra `/work/*.md` thì được đọc lại gắn vào kết quả trước khi container bị dọn.
- Toolset read-only KHÔNG có web-search generic (cố ý) — dùng `web.scrape` có kiểm; nếu nghề cần search thì thêm tool có-kiểm (như `academic.search`), không mở egress rộng.

### 6b. Định tuyến: chọn runtime tier + cơ chế multi-agent nào

Benchmark cho thấy điều dễ nhầm nhất KHÔNG phải chọn sai config mà là **dùng sai công cụ cho hình dạng việc**. Bảng quyết định:

| Hình dạng việc | Runtime tier | Cơ chế multi-agent |
|---|---|---|
| Báo cáo template / việc nhiều-vai có cấu trúc | `native` (mặc định) | **native team** (decompose→DAG→PIC→review) |
| Suy luận trên dữ liệu ĐỌC, không cần shell | `create_agent` | — (1 agent) |
| 1 báo cáo, vài nhánh ngữ cảnh LỚN cần tóm riêng biệt | `deep_agent` | **deep_team** (≤3 trợ lý con in-sandbox, v43) |
| Nhiều nhánh ĐỘC LẬP / nhiều deliverable | `native` | **native team** (KHÔNG deep_team) |
| Thật sự cần chạy shell / ghi file | `deep_agent` | — (hoặc deep_team nếu cần siloing) |

**Nguyên tắc cốt lõi:**
- **native team** = fan-out RỘNG: nhiều vai, nhiều deliverable, chạy đa tiến trình thật (đây là lợi thế cấu trúc). Cap: 7 step/DAG, concurrency 2 (chỉnh per-company qua `team_task_concurrency` trong `company.yaml`).
- **deep_team** (in-sandbox subagent) = siloing HẸP-SÂU: 2-3 ngữ cảnh lớn mỗi cái cần tóm tách bạch, gộp về MỘT deliverable. **KHÔNG dùng cho fan-out rộng** — benchmark cho thấy 5 nhánh vs cap 3 → gộp, đắt 3-7× mà không tốt hơn. Cap mặc định 3.
- `deep_agent` **chậm hơn mỗi step** vì mỗi step nhận một container sandbox mới, cách ly, tự-hủy — **cách ly đó là mục đích, không phải lỗi**. Việc no-shell cần nhanh → dùng `create_agent`/`native`.

**Knob per-company/agent (v41/v44) — chỉ nâng khi có nhu cầu nặng cụ thể; mặc định bảo vệ ca thường + giới hạn blast-radius:**

```yaml
agent_runtime:
  kind: deep_agent
  sandbox:
    provider: docker
    lease_seconds: 1800    # v41: cửa sổ sống container (mặc định 1800, tối đa 3600)
    mem_limit: 512m        # v44: trần RAM container (mặc định 512m, tối đa 4g) — nâng cho research nặng
deep_team: true            # v43: bật điều phối trợ lý con in-sandbox
deep_team_max_calls: 3     # v44: trần số lần giao trợ lý con (mặc định 3, kẹp [1,8])
```

## 7. Backup & khôi phục

```bash
./deploy/backup.sh /path/to/backups     # tar .data/ + profiles/ + registry.yaml + company-docs/
# cron hằng ngày:  0 2 * * *  /path/to/deploy/backup.sh /path/to/backups
```

`.env` (secrets) KHÔNG vào backup — khôi phục tay từ password manager. Khôi phục: giải nén
tar về repo root, chạy lại `install.sh`.

## 8. Kiểm tra sức khỏe

**Cài đặt → Sức khỏe hệ thống** trong web: bảng ✓/✗ từng tích hợp (OpenRouter, Atlassian,
Slack, MCP builds, GitHub, gws) + cảnh báo web_search-thiếu-key (v18). Mục lỗi kèm lệnh sửa.

## 9. Sự cố thường gặp

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| Giao việc xong "kẹt" không chạy | coordinator daemon không chạy | `uv run python -m src.runtime.service` |
| Văn phòng trống, giao việc không có ai | registry thiếu agent office | trang Đội → "Hồ sơ chưa trong đội" → Thêm |
| Nghiên cứu trả "xin phép tra cứu web" | thiếu Tavily/Brave key | thêm key ở Setup, hoặc tắt web_search |
| Bind LAN bị từ chối lúc khởi động | web-auth chưa bật | đặt `WEB_AUTH_PASSWORD_HASH` + `WEB_SESSION_SECRET` |
