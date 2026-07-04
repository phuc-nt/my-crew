# v7 M17 — Zero-friction install: installer + First-run Setup Wizard

2026-07-04 · ✅ Done

Mở v7 (zero-friction). Cửa vào sản phẩm: máy sạch → 1 lệnh → wizard trên browser nhập key + đặt mật khẩu → dashboard. CEO KHÔNG BAO GIỜ mở text editor. Đây là bề mặt nhạy nhất v7 (đường ghi secret mới), qua red-team plan trước khi cook.

## Làm gì
- **env_writer** (`src/server/env_writer.py`): atomic merge-write .env — giữ key/comment cũ, update in-place, append key mới, `.env.bak`, `os.replace`. **Whitelist key-name CỨNG** (`SETUP_WRITABLE_KEYS`): chỉ ghi key hợp lệ, TỪ CHỐI PATH/LD_PRELOAD/PYTHONPATH (env-injection→RCE). All-or-nothing khi gặp key lạ.
- **routes_setup** (`src/server/routes_setup.py`): `GET /status` (bool key-presence, không lộ value), `POST /env` (whitelist), `POST /test/{group}` (re-check integration_health với `override=True` để thấy key vừa ghi), `POST /finish` (đặt password → hash + session secret + marker → restart web).
- **Guard 4 tầng**: (1) khóa khi `setup_complete()` — marker `.setup-complete` BỀN; (2) localhost only (không tin X-Forwarded-For); (3) write-only; (4) whitelist.
- **Setup.tsx** wizard 5 bước (OpenRouter/Atlassian/Slack/GitHub + đặt mật khẩu), mỗi bước có nút "Kiểm tra kết nối". App check `/api/setup/status` TRƯỚC login → chưa setup thì hiện wizard.
- **install.sh** mở rộng: tự clone+build 3 MCP server vào `~/workspace/`, check gh auth, cài launchd, mở browser.

## Red-team fixes (đã code từ plan) + review fix
- **MAJOR-1 (plan)**: `.env` ghi KHÔNG hot-reload (`load_dotenv` không override os.environ, session secret bind-once ở create_app) → `finish` RESTART web service (`launchctl kickstart`), KHÔNG giả định "dashboard sống tức thì". Wizard hiện "đang khởi động lại".
- **MAJOR-2 (plan)**: khóa wizard bằng marker file BỀN, KHÔNG chỉ `auth_enabled()` — rotate/xóa hash không mở lại wizard (chống chiếm quyền). E2E chứng minh: xóa hash → marker vẫn khóa (410).
- **MINOR-2 (plan)**: whitelist key-name chống env-injection.
- **REVIEW C1 (CRITICAL — tôi tự tạo khi vá dev-flow, review bắt)**: fix dev-flow của tôi (OPENROUTER key ⇒ setup done) dùng CÙNG hàm `setup_complete()` cho cả `_guard` (khóa write) lẫn `/status` (show wizard). Hậu quả tệ hơn cái nó vá: wizard bước 0 ghi OPENROUTER → bước sau `_guard` thấy key → 410 → KHÔNG tới được đặt password → dashboard mở KHÔNG AUTH. Vá: TÁCH 2 câu hỏi — `wizard_locked()` (marker OR auth, dùng cho `_guard`) vs `wizard_should_show()` (thêm env-key clause, dùng cho `/status`). Test real-flow (openrouter→group→finish KHÔNG 410) + lock-vs-show-distinct làm guard tái phạm.
- **H1/M1/M2 (review)**: test cũ né key trigger (đổi OPENROUTER→GITHUB_REPO) che C1 → thêm test đi ĐÚNG đường openrouter; `.setup-complete`+`.env.bak` vào .gitignore (commit nhầm sẽ tắt wizard fresh-clone); bỏ BIND_HOST khỏi wizard whitelist (set 0.0.0.0 chưa finish → wedge startup).
- **BIND_HOST an toàn**: wizard whitelist có BIND_HOST; nếu CEO set 0.0.0.0 nhưng chưa finish (auth off) → restart → `assert_bind_safe` refuse (fail-loud M16). Verify live.

## Verified
1070 pytest (16 mới: env_writer whitelist/atomic/all-or-nothing/presence-bool; setup guard/marker-durability/localhost/finish/dev-flow-regression) + 42 vitest (Setup wizard 3) + ruff + build. **E2E full flow**: status chưa-setup → ghi key → status bool không-lộ-value → inject PATH=400 → finish → marker+hash ghi .env → mọi endpoint 410 (kể cả finish lại) → xóa hash marker VẪN khóa.

## Bài học
- **Đường ghi secret mới = fail-loud + khóa BỀN + whitelist, không "khóa mềm"**: khóa theo trạng thái phụ (hash) thì mất hash = mở cửa lại. Marker file độc lập là khóa thật. Whitelist key-name chống env-injection (bề mặt ai cũng quên tới khi bị RCE).
- **`.env` ghi ≠ có hiệu lực**: `load_dotenv` không override os.environ — bài học lặp lại (M15b hash, M16 secret, giờ M17). Config nhạy phải restart, không hot-swap. Ghi vào memory từ lâu, giờ áp đúng.
- **Thêm cửa "first-run" dễ chặn nhầm người cũ**: check "chưa setup" phải phân biệt "máy mới toanh" vs "đã cấu hình tay chưa đặt password" — nếu không, mọi user M16 bị ép qua wizard. Regression im lặng nếu không test đúng đường load thật.
- **MỘT hàm cho HAI câu hỏi = bug (C1)**: "show wizard?" (frontend UX) và "lock writes?" (backend security) TRÔNG giống nhau nhưng KHÁC — gộp làm wizard tự khóa mình giữa chừng + hở dashboard không auth. Bài học: khi 1 predicate phục vụ cả UX lẫn security gate, TÁCH ngay — chúng tiến hóa theo hướng đối lập (UX muốn "đã xong sớm để bỏ qua", security muốn "chưa khóa tới khi thật sự xong"). Và **fix vội một regression có thể đẻ CRITICAL** — mọi vá phải test đúng đường thật, không chỉ đường mình vừa nghĩ.

## Unresolved / next
1. Restart từ web request (`launchctl kickstart` từ tiến trình web) — cần verify quyền trên máy launchd thật (Unresolved plan). Fallback KeepAlive.
2. Đường dev (uvicorn tay): finish set flag, restart thủ công — chưa auto.
3. M18a: agent chạy-ngay (wizard bước Telegram) + trang agent hợp nhất.
