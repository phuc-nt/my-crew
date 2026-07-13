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
