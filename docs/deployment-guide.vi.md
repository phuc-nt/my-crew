# Hướng dẫn Cài đặt & Vận hành — my-crew

> **Bản EN là canonical:** [deployment-guide.md](deployment-guide.md)
>
> Hướng dẫn cài đặt, chạy, cấu hình hệ thống cho người vận hành (kỹ thuật).
> **Cho người dùng cuối (CEO / quản lý):** xem [huong-dan-su-dung.md](huong-dan-su-dung.md).
> **Cập nhật:** 2026-07-18.

## 1. Yêu cầu

| Công cụ | Ghi chú |
|---|---|
| Python 3.12+ | Qua `uv` (venv pin 3.12); KHÔNG dùng global 3.14+ |
| `uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js + npm | Build FE + MCP servers |
| `git` | |
| `gh` (GitHub CLI) | `gh auth login` (bước tương tác, không tự động) |
| `gws` (tùy chọn) | Chỉ cho hr-pack (Google Sheets) |

### Tài khoản & Token

Điền **trong trình duyệt Setup Wizard** (KHÔNG qua terminal). Bắt buộc:

- **OpenRouter** (LLM): 1 API key. Giới hạn $50/tháng, tự dừng.
- **Atlassian** (Jira + Confluence): site, email, 1 token (chung cho cả hai).
- **Slack** (browser-token): xoxc + xoxd token, tên team, kênh báo cáo.
- **GitHub**: qua `gh auth login` (CLI-stored, không trong `.env`).

Tùy chọn:

- **Tavily hoặc Brave** (web search): chỉ nếu dùng vai trò Nghiên cứu.
- **SMTP**: chỉ nếu xuất báo cáo qua email.
- **Telegram**: chỉ nếu bật mobile command/alert cho agent.

### 3 MCP Server

Node.js stdio. `install.sh` cài từ npm mặc định; `--mcp-dev` để clone + build:

- **Jira** → [github.com/phuc-nt/jira-cloud-mcp-server](https://github.com/phuc-nt/jira-cloud-mcp-server) (v4.2.0)
- **Confluence** → [github.com/phuc-nt/confluence-cloud-mcp-server](https://github.com/phuc-nt/confluence-cloud-mcp-server) (v1.5.0)
- **Slack** → [github.com/phuc-nt/slack-browser-mcp-server](https://github.com/phuc-nt/slack-browser-mcp-server) (v1.3.0)

Nếu không ở chỗ mặc định (`~/workspace/*-mcp-server`), trỏ qua `JIRA_MCP_DIST`, `CONFLUENCE_MCP_DIST`, `SLACK_MCP_DIST` trong `.env`.

---

## 2. Cài Một Lệnh (macOS + launchd, production)

```bash
git clone git@github.com:phuc-nt/my-crew.git && cd my-crew
./deploy/install.sh
```

Script tự chạy **7 bước**:

1. **Preflight** — kiểm công cụ (`uv`, `node`, `git`, `gh`); in lệnh cài nếu thiếu.
2. **`uv sync`** — cài thư viện Python.
3. **Build web SPA** — compile React sang temp dir, rồi swap nguyên tử (không phá live server).
4. **Cài 3 MCP server** — từ npm (mặc định) hoặc clone+build (với `--mcp-dev`).
5. **Bootstrap `.env`** — copy template lần đầu (v18); secrets chỉ qua wizard trình duyệt.
6. **Cài launchd service** — coordinator + web. Reload chỉ khi plist hoặc SPA đổi (idempotent; không giết agent chạy).
7. **Health check** — báo ✓/✗ từng tích hợp trước mở trình duyệt.

**An toàn gọi lại:** `./deploy/install.sh` sau `git pull` là no-op nếu không đổi gì. KHÔNG khởi động lại service không cần thiết.

---

## 3. Setup Wizard (Trình Duyệt — Con Đường Bí Mật)

Lần đầu, trình duyệt mở **Setup Wizard** với các bước tương tác. Mỗi bước có nút "Kiểm tra kết nối":

1. **OpenRouter** — dán API key.
2. **Atlassian** — site, email, token, mã project Jira (e.g., `SCRUM`).
3. **Slack** — xoxc, xoxd, tên team, kênh báo cáo.
4. **GitHub** — repo; kiểm `gh auth login`.
5. **(Tùy chọn) Web Search** — toggle Tavily/Brave, dán key (bỏ qua nếu Nghiên cứu không dùng).
6. **Mật khẩu Dashboard** — đặt bcrypt-hash login.

> **Bảo mật:** Bí mật **chỉ** đi qua wizard. Ghi `.env` (gitignored); không qua terminal hay URL. Wizard tự khóa sau xong; không mở lại được.

---

## 4. Quick Start (30 giây, v49)

Muốn thấy kết quả NGAY mà không cần toàn bộ tích hợp:

```bash
echo 'OPENROUTER_API_KEY=sk-or-...' >> .env
my-crew quickstart      # hoặc: python -m my_crew.entrypoints.mpm quickstart
```

Chạy báo cáo hằng ngày agent mặc định ở chế độ **dry-run** (log ý định; không ghi ngoài). An toàn thử.

### Tạo Đội Mẫu

Để tạo agent mẫu + giữ lại:

```bash
my-crew crew init           # tạo 5 agent mẫu
uv run python -m my_crew.runtime.service &     # khởi động bộ điều phối
# hoặc:
my-crew serve               # foreground: web + coordinator
```

Sau `crew init`, trang **Đội** hiện trạng thái bộ điều phối.

---

## 5. Chạy Thủ Công (dev, không launchd)

```bash
uv sync
cd web && npm install && npm run build && cd ..
PORT=8765 uv run python -c "from my_crew.server.app import main; main()" &
uv run python -m my_crew.runtime.service &
# → http://127.0.0.1:8765
```

- **Web:** bind `BIND_HOST` (mặc định 127.0.0.1) port `PORT` (mặc định 8765). Bind LAN bị chặn trừ khi bật auth.
- **Coordinator daemon:** **bắt buộc** để đội dispatch việc. Không chạy → banner đỏ cảnh báo.

---

## 6. Docker Compose (cross-platform, auth-first)

```bash
cd deploy/docker/
cp my-crew.env.example my-crew.env
```

Tạo auth **trước** khởi động (R3: bí mật phải set trước bind 0.0.0.0):

```bash
docker compose run --rm --no-deps my-crew my-crew web hash-password
# → dán bcrypt hash vào my-crew.env (WEB_AUTH_PASSWORD_HASH)
# → tạo WEB_SESSION_SECRET: openssl rand -hex 32
# → set OPENROUTER_API_KEY trong my-crew.env
```

Khởi động:

```bash
docker compose up -d
# → http://127.0.0.1:8765 → đăng nhập → Setup Wizard
```

Dữ liệu người dùng (`.env`, `registry.yaml`, `profiles/`, `.data/`) lưu trên volume `my-crew-data`. `docker compose down` giữ dữ liệu; `docker compose up` tiếp tục.

---

## 7. Cấu Hình

| File | Vai trò | Git |
|---|---|---|
| `.env` | Secrets (token, key) | ignored |
| `registry.yaml` | Đội nhân sự — **dữ liệu người dùng (v18)** | ignored (template: `registry.example.yaml`) |
| `company.yaml` | Tên công ty, coordinator, budget cap, auto-confirm | ignored |
| `profiles/<id>/` | Hồ sơ agent (YAML + SOUL/PROJECT/MEMORY) | ignored (trừ default/ + templates/) |
| `company-docs/` | Tài liệu công ty inject vào agent | ignored |

> **v18 Quan trọng:** `registry.yaml` **không** trong git. Fresh checkout auto-bootstrap từ `registry.example.yaml`. **Không bao giờ `git checkout registry.yaml`** — mất đội.

### User State Root (`MY_CREW_HOME`)

Nơi lưu `.env`, `registry.yaml`, profiles, `.data/`:

**Thứ tự phân giải:**
1. Biến `MY_CREW_HOME` (nếu set)
2. Root git checkout (operator dev; dữ liệu live trong repo)
3. `~/.my-crew/` (user đã install, mặc định)

### Runtime Tier: Chọn Engine Cho Agent

**Mặc định: `native`** — DAG cố định (perceive → analyze → compose → deliver). Rẻ, xác định, tốt cho báo cáo template. **Giữ native cho báo cáo hằng ngày.**

**Suy luận mở:** `create_agent` (LLM tự chọn tool, read-only) hoặc `deep_agent` (shell trong Docker sandbox cách ly).

```yaml
# profiles/<id>/profile.yaml

# Tuỳ chọn 1: LLM tự chỉ đạo công cụ
agent_runtime: create_agent
# hoặc với giới hạn vòng lặp:
agent_runtime:
  kind: create_agent
  runtime_loop_limit: 12

# Tuỳ chọn 2: Shell tự chủ trong Docker sandbox (chậm, cần Docker daemon)
agent_runtime:
  kind: deep_agent
  sandbox:
    provider: docker
    lease_seconds: 1800    # container lifetime (default 1800s, max 3600s)
    mem_limit: 512m        # container RAM (default 512m, max 4g)
```

**Tuỳ chọn per-team (v44):**

```yaml
deep_team: true                 # bật subagent in-sandbox (v43)
deep_team_max_calls: 3          # cap trợ lý (default 3, range [1,8])
```

**v45 Smart Routing:** Team task tự routing per-step — no-shell chạy `create_agent` (0 Docker); `needs_shell` chạy `deep_agent`. Một agent deep_agent không spin container cho mọi bước; chỉ bước cần shell.

### Docker Sandbox Cho `deep_agent`

**Cần:** Docker Desktop HOẶC `colima` (nhẹ, không GUI):

```bash
brew install colima && colima start
```

Daemon offline → deep_agent error "sandbox unavailable". Check **Health** panel trước giao shell work.

**Giới hạn:** deep_agent sandbox **không khả dụng TRONG container** — nếu chạy my-crew qua Docker, agent không thể spin sandbox lồng. Cần deep_agent? Chạy host hoặc Docker-in-Docker.

---

## 8. Go Live: DRY_RUN & Trust Mode

### Dry-Run Toggle

Mặc định, agent **log ý định mà không ghi ngoài.**

```bash
DRY_RUN=false my-crew serve       # bật ghi ngoài (Slack post, PR merge, v.v.)
```

Đặt trong `.env`:

```env
DRY_RUN=false
```

### Trust Mode (per agent)

**Autonomous (mặc định):** Hành động gửi ngoài công ty (post Slack, merge PR) **chạy ngay** + audit. Không cần CEO duyệt.

```yaml
safety:
  trust_mode: autonomous
```

**Guarded (tuỳ chọn):** Hành động đó **chờ duyệt** CEO trước chạy. CEO click "Duyệt" hoặc "Từ chối" ở tab **Duyệt**.

```yaml
safety:
  trust_mode: guarded
```

> **Hard-deny (Lớp A):** Hành động mất dữ liệu vĩnh viễn (xoá, lộ credential) **không bao giờ cho phép**, kể cả guarded. Xem [action-gateway-explainer.md](action-gateway-explainer.md).

---

## 9. Backup & Khôi Phục

```bash
./deploy/backup.sh /path/to/backups
# → tar .data/, profiles/, registry.yaml, company-docs/
```

**Secrets (.env) KHÔNG backup.** Khôi phục tay từ password manager. Khôi phục dữ liệu:

```bash
cd /path/to/repo
tar -xzf /path/to/backups/my-crew-TIMESTAMP.tar.gz
./deploy/install.sh
```

**Cron hằng ngày (02:00):**

```bash
0 2 * * * /path/to/deploy/backup.sh /path/to/backups
```

---

## 10. Health Check

**Settings → Sức khỏe hệ thống** trong web. Bảng ✓/✗:

- OpenRouter, Atlassian, Slack, GitHub, MCP, Docker, web search.

Mỗi lỗi show lệnh khắc phục. Docker probe có timeout. ✗ chỉ ảnh hưởng agent deep_agent — đội no-shell OK.

### Warm Sandbox Image (tuỳ chọn)

Pre-warm Docker image trước bước deep_agent đầu:

```bash
my-crew sandbox prepull
```

Idempotent: image có → no-op. Daemon offline → in thông báo rõ (không crash).

---

## 11. Sự Cố Thường Gặp

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| Giao việc xong kẹt không chạy | Coordinator không chạy | `uv run python -m my_crew.runtime.service` |
| Đội trống, không có agent | Registry thiếu agent | **Đội** → "Hồ sơ chưa trong đội" → **Thêm** |
| Nghiên cứu nói "xin phép web search" | Thiếu Tavily/Brave key | Thêm ở Setup, hoặc tắt web_search |
| Bind LAN từ chối lúc khởi động | Web auth chưa bật | Set `WEB_AUTH_PASSWORD_HASH` + `WEB_SESSION_SECRET` |
| deep_agent "Docker sandbox không khả dụng" | Docker daemon không chạy | Chạy Docker Desktop hoặc `colima start` |
| Bước deep_agent đầu chậm | Image chưa có, phải pull | Warm: `my-crew sandbox prepull` |
| Route mới không xuất hiện sau `git pull` | Dev server chạy tay không reload | Khởi động lại web + coordinator, hoặc `./deploy/install.sh` |

---

## 12. Upgrade Path & Breaking Change

### v51 Rename Thông báo

**Sau upgrade v51**, source rename (`src/` → `my_crew/`). Nếu upgrade hệ thống chạy:

1. **Gọi lại install.sh để render launchd plist:**
   ```bash
   git pull origin main
   ./deploy/install.sh
   ```

2. **Kiểm orphan process cũ** (500 mọi route):
   ```bash
   lsof -nP -iTCP:8765
   # Kill process cũ giữ port 8765
   ```

3. **Restart coordinator + web nếu upgrade <v51:**
   ```bash
   launchctl stop com.phucnt.my-crew-coordinator
   launchctl stop com.phucnt.my-crew-web
   ./deploy/install.sh
   ```

### DRY_RUN Mặc Định

`DRY_RUN=true` là mặc định an toàn. Lần deploy đầu, agent log ý định nhưng KHÔNG ghi ngoài. Set `DRY_RUN=false` khi sẵn sàng agent hoạt động.

---

## 13. Hiệu Năng & Mở Rộng

### Memory & CPU

**Tối thiểu:** 2 GB RAM, 2 CPU.
**Đề xuất:** 4 GB RAM, 4 CPU (chạy deep_agent nhiều task).
**Docker:** Set `mem_limit` trong `docker-compose.yaml` nếu cần (mặc định 512m/sandbox).

### Concurrency Knob

```yaml
# company.yaml
team_task_concurrency: 2        # max parallel team task (default 2)
deep_team_max_calls: 3          # max subagent (default 3)
```

---

## 14. Production Checklist

- [ ] Toàn bộ credential ở Setup Wizard (OpenRouter, Atlassian, Slack, GitHub).
- [ ] `WEB_AUTH_PASSWORD_HASH` + `WEB_SESSION_SECRET` set nếu bind LAN.
- [ ] `DRY_RUN=false` set trong `.env` để ghi ngoài.
- [ ] Backup script cấu hình: `0 2 * * * /path/to/deploy/backup.sh /path/to/backups`.
- [ ] Coordinator daemon chạy (check **Health** ✓).
- [ ] Health panel ✓ toàn bộ tích hợp dùng.
- [ ] Báo cáo test đầu chạy OK (check **Hoạt động**).
- [ ] Agent giao việc, watch 1 chu kỳ (compose → execute → report).
- [ ] Telegram bot tuỳ chọn nhưng đề xuất (real-time alert).

---

## Tham Khảo Thêm

- **Vận hành hằng ngày:** [huong-dan-su-dung.md](huong-dan-su-dung.md)
- **Hiểu guardrail:** [action-gateway-explainer.md](action-gateway-explainer.md)
- **Kiến trúc & quyết định:** [project-overview-pdr.md](project-overview-pdr.md) · [system-architecture.md](system-architecture.md)
- **Lịch sử xây dựng:** [journals/](journals/)
