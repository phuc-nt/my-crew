# v51 Phase 01 — Packaging core: `my-crew` cài được, state rời repo

**Ngày:** 2026-07-18 · **Commits:** `ec36db5` → `5fd0fa4` (5) · **Suite:** 2351 BE + 201 FE, ruff sạch · **Plan:** `plans/260718-0700-productize-my-crew-publishable-tool/`

## Bối cảnh

Audit 4-nguồn (my-crew vs openclaw/hermes/omnigent) kết luận: khoảng cách để publish không nằm ở chất lượng code mà ở lớp release engineering. CEO chốt mục tiêu "tool người lạ cài và chạy được". Phase 01 phá 3 blocker gốc: package top-level tên `src` không ship PyPI được, CLI không cài được (`python -m src.entrypoints.mpm`, không `--help`), user-state dính cứng vào repo root.

## Đã làm

1. **Rename cơ học `src/` → `my_crew/`** (~530 file, 1 commit riêng thuần máy): imports, monkeypatch strings, plists, install.sh, vite outDir, pyproject, docs active (journals/archive giữ nguyên — hồ sơ lịch sử).
2. **CLI argparse**: `[project.scripts] my-crew`, `--help` mô tả từng group + examples, `--version` đọc `importlib.metadata`, version 0.1.0. Giữ nguyên contract return-int (usage lỗi = 2, "unknown subcommand" giữ nguyên text) và lazy-import per-command để test monkeypatch được.
3. **Seam `MY_CREW_HOME`**: `resolve_home()` thuần — env > checkout có `.git` (giữ nguyên hành vi máy vận hành) > `~/.my-crew` (installed). 8 file user-state chuyển theo (.env, registry, company.yaml, profiles user, company-docs, .data, .setup-complete); resource ship kèm (templates, domain-packs, model_prices, registry.example) giữ package-relative. mkdir home tại seam.
4. **Fix bug v49 lộ ra khi UAT**: guard quickstart chỉ đọc `os.environ` trong khi hint bảo user đặt key vào `.env` — key chỉ nằm trong `.env` là fail. Giờ nạp `MY_CREW_HOME/.env` trước khi check.

## Review bắt được gì (code-reviewer, SHIP_WITH_FIXES)

- **H1** `scripts/demo-mode.sh` sót 3 ref `src.*` — nặng nhất là guard pgrep chống chạy-đôi coordinator match tên module cũ → **fail open** (lỗi đúng loại v16 từng phải vá). Sed theo path `deploy/` mà quên `scripts/`.
- **H2** Banner recovery FE dặn CEO chạy `python -m src.runtime.service` — lệnh chết đúng lúc coordinator chết. Nguồn `.tsx` nằm ngoài mọi pattern sed py/sh/plist. Fix + rebuild bundle committed.
- **M3** Test quickstart thứ 3 nạp `.env` THẬT của máy dev vào process pytest (xanh/đỏ tùy nội dung .env máy). Pin `MY_CREW_HOME=tmp_path`.

## Bài học

- **Sed rename phải quét cả bề mặt "kể lại" module**: string trong `.tsx`/`.sh` ngoài package không nằm trong grep `--include="*.py"`. Lần sau: grep tên module cũ TOÀN repo (mọi extension) làm bước leftover-check, không chỉ các thư mục "chắc là có".
- **Biến local trùng tên package** (`src` = source string trong 2 file test) bị `\bsrc\.` ăn nhầm → NameError. Grep-kiểm biến trần trước khi sed là chưa đủ nếu filter của chính mình che mất pattern.
- **Pipe `| tail` nuốt exit code** → ruff đỏ vẫn lọt commit (phải amend). Verify gate phải chạy lệnh trần hoặc `set -o pipefail`.
- **`load_dotenv` trong code được test = rủi ro nạp secret thật vào suite** — mọi đường load .env phải patchable qua seam (`MY_CREW_HOME` module attr) và test phải pin nó.
- **CWD dính giữa các lệnh shell** (`cd web` ở lệnh trước) làm 2 lượt lệnh sau chạy sai chỗ, tạo "báo động giả" mất thư mục static.

## Migration máy vận hành (đã làm ngay, CEO duyệt)

`./deploy/install.sh` re-render 2 plist sang `my_crew.*` + reload. **Vấp thêm**: một process web CŨ (chạy từ trước rename, code `src.*` còn trong RAM) vẫn giữ port 8765 — mọi route lazy-import trả 500, còn service web MỚI của launchd không bind được port nên crash-loop exit 1; installer health gate vì thế báo nhầm "dashboard not yet set up". Fix: kill PID cũ + `launchctl kickstart` → web 200, coordinator heartbeat sống, `/api/setup/status` completed=true. **Bài học: sau rename module, restart-on-change của installer không đụng được orphan listener có trước — upgrade-check phải soi `lsof` port, không chỉ launchd.**

## Còn treo

- Installed-mode (`~/.my-crew`) mới đúng ở mức path; templates/domain-packs từ wheel là việc phase 03.
- Docs phase 02/05: ghi loud "sau upgrade chạy lại ./deploy/install.sh + kiểm orphan listener".
