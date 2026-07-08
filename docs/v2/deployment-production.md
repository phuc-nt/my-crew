---
title: "Triển khai production (v6 M16)"
description: "Cài đặt 1 lệnh, bật auth, backup — đưa hệ thống từ máy dev thành công ty dùng thật."
status: stable
created: 2026-07-04
---

# Triển khai production

> Đưa hệ thống từ "chạy trên máy dev" thành "công ty dùng thật": 1 lệnh cài, có đăng nhập, có backup. Target mặc định: **Mac / Mac mini + launchd**. (Linux/docker: xem cuối trang.)

## Mô hình an toàn

1 CEO, chạy trong LAN công ty. Nút **Duyệt** trên web mở khóa hành động Lớp B (tạo ticket, post external…) — nên **auth chính là lớp bảo vệ Lớp B**, không phải trang trí. Single-user session login là đủ (không cần SSO/multi-tenant).

## Cài đặt (1 lệnh, v10 M26 hardened)

```bash
git clone <repo> && cd my-project-manager
cp config.example.env .env        # rồi điền các key (xem bên dưới)
./deploy/install.sh
```

**`install.sh` (v10 M26 hardening + v11 P4 npm MCP install):**
1. **Preflight fail-loud**: kiểm `uv`/`node`/`npm`/`git` → in lệnh `brew install` nếu thiếu, exit 1. `gh` = warning (login interactive, không chặn).
2. **Restart-only-on-change (F6)**: so plist render vs đã cài → chỉ `launchctl unload/load` nếu khác. Tránh kill agent run giữa chừng.
3. **SPA build temp + swap**: `vite build` → temp dir, `rsync` vào serve dir CHỈ khi khác (không interrupt live client).
4. **MCP servers từ npm (mặc định)**: `npm install --prefix ./.mcp-servers` với version pin
   chính xác (idempotent — chạy lại = no-op), ghi `*_MCP_DIST` vào `.env` khi còn thiếu. 3 package
   đã publish (mcp-jira-cloud-server 4.2.0 / confluence-cloud-mcp-server 1.5.0 /
   slack-browser-mcp-server 1.3.0). Cờ `--mcp-dev` giữ đường tải + build 3 repo cũ vào
   `~/workspace/` (dùng khi dev server local). Máy cũ còn `*_MCP_DIST` trỏ build cũ hơn min →
   installer cảnh báo cách migrate (red-team F5).
5. **Health gate**: 3 MCP build (npm prefix hoặc clone dir, tuỳ nhánh) + `gh auth` + dashboard auth presence → bảng ✓/✗ trước khi "xong".
6. **HTTPS clone** (khớp docs, bỏ SSH `git@`) khi dùng `--mcp-dev`.
7. **bash 3.2 compat** (macOS default): map repo→env-var/npm-package via `case` function (no `declare -A`).

Script idempotent: re-run không phá gì (restart=no-op nếu config unchanged).

## Bật đăng nhập (BẮT BUỘC trước khi mở ra LAN)

```bash
# 1. Tạo hash mật khẩu (nhập ẩn, không vào shell history):
uv run python -m src.entrypoints.mpm web hash-password
# → dán WEB_AUTH_PASSWORD_HASH=... và WEB_SESSION_SECRET=... vào .env

# 2. (tuỳ chọn) đổi tên đăng nhập:
#    WEB_AUTH_USERNAME=ceo    trong .env
```

Khi `WEB_AUTH_PASSWORD_HASH` chưa đặt → dashboard **không có auth** (chỉ dùng localhost dev). Cơ chế bảo vệ: nếu đặt `BIND_HOST` khác `127.0.0.1` mà auth chưa bật → **dịch vụ từ chối khởi động** (fail loud), tránh vô tình phơi dashboard không mật khẩu ra mạng.

## Truy cập từ máy khác trong công ty

```bash
# trong .env, CHỈ sau khi đã bật auth ở trên:
BIND_HOST=0.0.0.0
PORT=8765
```

Rồi mở `http://<ip-máy-chủ>:8765` từ máy khác trong LAN. Truy cập từ xa (ngoài công ty): dùng **Tailscale** hoặc VPN — không mở thẳng ra internet (chưa có HTTPS; TLS là việc của reverse proxy nếu cần).

## Backup / Restore

```bash
# Backup thủ công (KHÔNG gồm .env — secrets phục hồi từ password manager):
./deploy/backup.sh                 # → backups/mpm-backup-<timestamp>.tar.gz

# Cron backup hằng ngày 2h sáng (crontab -e):
0 2 * * *  /đường-dẫn/deploy/backup.sh /đường-dẫn/backups

# Restore (dừng service trước):
launchctl unload ~/Library/LaunchAgents/com.mpm.{web,service}.plist
./deploy/restore.sh backups/mpm-backup-<timestamp>.tar.gz
launchctl kickstart -k gui/$(id -u)/com.mpm.service
launchctl kickstart -k gui/$(id -u)/com.mpm.web
```

Backup gồm `.data/` (sqlite + audit + tasks) + `profiles/` + `registry.yaml`. Restore đưa agent chạy tiếp đúng chỗ dừng — approval/audit/task còn nguyên.

## Vận hành

| Việc | Lệnh |
|---|---|
| Xem log web | `tail -f .data/web.log` |
| Xem log agent (scheduler) | `tail -f .data/service.log` |
| Khởi động lại web | `launchctl kickstart -k gui/$(id -u)/com.mpm.web` |
| Dừng tất cả | `launchctl unload ~/Library/LaunchAgents/com.mpm.{web,service}.plist` |
| Nghiệm thu | Đi hết [uat-checklist.md](uat-checklist.md) |

## Linux / Docker (chưa build sẵn)

Target chính là Mac + launchd. Trên Linux: chạy `uv run python -m src.server.app` (web) + `uv run python -m src.runtime.service` (scheduler) dưới systemd/supervisor với đúng biến môi trường `.env`. Docker compose có thể thêm sau khi có máy Linux thật — không nằm trong M16 (YAGNI).

## Unresolved

- HTTPS trong LAN thuần: chưa cần; thêm reverse proxy (Caddy/nginx) khi truy cập từ xa.
