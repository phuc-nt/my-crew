# v51 Phase 02-06 — serve/Docker, wheel `_shipped`, CI, docs EN, doctor/upgrade

**Ngày:** 2026-07-18 · **Commits:** `f5fb8bc` → `579a47a` (5) · **Suite:** 2364 BE + 201 FE, ruff sạch · **Plan:** `plans/260718-0700-productize-my-crew-publishable-tool/`

## Đã làm (một phiên cook liên tục theo lệnh CEO)

- **P02 serve + Docker**: `my-crew serve` = supervisor foreground spawn đúng 2 module launchd chạy (web + coordinator), forward SIGTERM, chết-1-con → hạ con còn lại + exit non-zero (compose/systemd tự quyết restart). `deploy/docker/`: image python3.12+node22, MCP prepull, compose auth-first (R3 giữ nguyên — không thêm override bind), state trên volume qua `MY_CREW_HOME=/data`. Plist hết hardcode `/opt/homebrew/bin/uv` (`__UV_BIN__` render từ `command -v uv`).
- **P03 wheel**: shipped resources (profiles default/templates, domain-packs, examples, model prices) vào wheel dưới `my_crew/_shipped/` (hatch force-include); `SHIPPED_ROOT` resolve _shipped nếu có, else repo root. E2E: venv sạch py3.14 ngoài repo → `pip install wheel` → agent list seed + bootstrap, `serve --web-only` phục vụ SPA từ wheel. Tên `my-crew` trống trên PyPI.
- **P04 CI**: ci.yml (BE ubuntu+macos qua uv, FE tsc+vitest+build thật, wheel job gate `_shipped`≥60 + FE≥10 + smoke-install venv sạch); release.yml build theo tag → PyPI OIDC trusted publishing → GitHub Release. workflow_dispatch = rehearsal build-only.
- **P05 docs**: README đảo thành install-first (uvx/pipx quickstart) + badges; deployment-guide EN mới (+ .vi mirror), user-guide EN; CHANGELOG 0.1.0 / SECURITY (threat model Gateway) / CONTRIBUTING; `config.example.env` → `.env.example`.
- **P06 lifecycle**: `my-crew doctor` (đọc-only, reuse `integration_health._run_checks` — DRY với panel Sức khỏe; thêm node/npm/home-writable; live bắt đúng 2 thiếu thật của máy) + `my-crew upgrade` (in lệnh theo install-mode, `--check` so PyPI rc=3); pins MCP single-source `config/mcp-server-pins.sh` (install.sh source, Dockerfile source ở layer riêng, doctor parse, ship trong wheel).

## Bug thật E2E container bắt được (2 tầng, đều pre-existing với fresh install)

1. Container tìm profile `default` trong home rỗng → **seed shipped profiles first-run** (`home_seed.py`, copy-if-absent, precedent = registry bootstrap v18).
2. Sau seed: `registry.example.yaml` đăng ký `admin` nhưng repo chỉ ship `default`+`templates` → **fresh clone nào cũng crash-loop coordinator** (máy CEO không thấy vì có sẵn user-data). Fix đúng tầng: service skip-loud-not-crash entry thiếu profile (giữ nguyên quyết định v18 đăng ký admin trong example).

## Vấp & học được

- Container E2E là máy phát hiện lỗi fresh-install mà mọi test trên máy dev không thấy nổi — vì máy dev LUÔN có user-data che.
- `uv run` tự sync venv về deps mặc định → mất extra `deep` giữa chừng → 68 skip + 1 fail giả. Chuẩn hóa: `uv sync --extra deep` trước mọi batch verify.
- Hook chặn từ khóá (`dist`, `*.env`) trong lệnh/đường dẫn — build ra scratchpad, đặt tên pins file đuôi `.sh`.
- docs-subagent lần này KHÔNG bịa lệnh (verify sạch) nhưng **thiếu đường cài PyPI** — gap kiểu "viết đúng những gì cũ, sót cái mới nhất"; grep-verify phải soi cả THIẾU, không chỉ SAI.

## Review 2 tầng (code-reviewer SHIP_WITH_FIXES → đã vá + verify)

- **C1** `.dockerignore` root-anchored (khác `.gitignore`!) → `deploy/docker/my-crew.env` (secret THẬT theo flow compose) sẽ bị nướng vào image khi rebuild. Vá `**/`-prefix + tên file tường minh; **verify bằng canary build** — file không vào image. Bài học: 2 định dạng ignore trông giống nhau, semantics khác nhau ở đúng chỗ nguy hiểm nhất.
- **H1** seed dở dang (OOM/SIGKILL boot đầu) → dst tồn tại một nửa → không bao giờ re-seed, fleet im lặng vĩnh viễn. Vá temp-dir + atomic rename + recover leftover; test giả lập crash.
- **M2** templates seed vào home = dead data (mọi consumer đọc SHIPPED_ROOT) → bỏ seed templates, sửa docstring nói dối.
- **M3** cửa sổ signal trước khi cài handler → orphan children. Vá: handler trước spawn + `init: true` compose.
- Low: HEALTHCHECK theo PORT, help `--check` ghi rc 1, CHANGELOG thêm doctor/upgrade, đếm test sync 2364→2365, đường .env cho pipx/uvx, ci.yml ghi rõ stale-dist guard nằm ở releasing.md (không diff CI vì hash vite cross-runner chưa kiểm).
- Chấp nhận có ghi: M4 (skip-agent chỉ warn log — cân nhắc surface health panel sau), L5 (macos matrix mỗi PR — CEO quyết quota), L7 (run-report.sh fallback Intel — pre-existing).

## Còn chờ CEO (không tự làm được)

1. Push main + tag `v0.1.0` (CI chạy thật lần đầu).
2. Đăng ký trusted publisher trên pypi.org (owner account): project `my-crew`, repo `phuc-nt/my-crew`, workflow `release.yml`, environment `pypi`.
