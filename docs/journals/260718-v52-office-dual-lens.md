# v52 — Office dual-lens: một văn phòng, hai ống kính

**Ngày:** 2026-07-18 · **Commits:** 4 (P1 visuals → P2 toggle+panels → P3 endpoints+views → P4 review-fix+docs) · **Suite:** 2370 BE + 211 FE · **Plan:** `plans/260718-1528-office-dual-lens-ui-upgrade/`

## Bối cảnh & quyết định

Brainstorm sau v0.1.0: dual-mode v25 chỉ gate nav, backend v26-v50 nhiều capability không có mặt UI, office 3D **nuốt im lặng `failed` thành idle**. CEO chốt 4 hướng: chung màn hình 2 vai, toggle header + per-view density, 3D kể chuyện + panel kể số, scope cả 4 gap (captures/budget/failure-health/search). Ràng buộc cứng giữ trọn: 0 write-path mới, allowlist SSE không đổi, low-mode chỉ nhận desk-lỗi + verdict flash, mode ≠ permission.

## Đã làm

- **P1 (thuần FE — data đã trên wire):** state `error` (desk đỏ pulse + bubble ⚠, hết khi dispatch kế), verdict flash vòng sàn xanh/cam fade 3s **theo ts event** (SSE replay không re-flash), 🔒 sandbox badge join board bằng `pic_id`/`room_id` (không title-match; semantic task-level — stream không mang tier). 2D fallback parity (label lỗi + cột Kiểm định).
- **P2:** toggle 👁/🔬 lên header (Settings giữ mirror); high-mode: Health strip (beat + doctor checks + budget chip) + Desk Inspector (click desk → step/pha/engine/cost, fetch-on-open, chỉ khi PIC).
- **P3:** router mới `routes_observability.py` — 3 GET read-only sau auth: `/api/budget` (sum per-agent, skip profile thiếu), `/api/captures` (+detail), `/api/search` (FTS5, escaping sẵn trong module); UI: Captures explorer (ADVANCED_NAV), search box header, budget gauge.
- **P4:** review SHIP_WITH_FIXES → vá cả 4 (M1 attempt_id trên event failed/clarify — chống desk đỏ GIẢ từ zombie worker; Low#1 board-leak race; Low#2 clock-skew; M2 sweep throttle 30s); docs EN+VN mục dual-lens; UAT browser thật.

## UAT browser thật (instance riêng 8898, auth-off, data thật read-only)

PASS máy: toggle low↔high tức thì (low sạch — không strip/search/advanced), strip live `♥ 5s · 💰 $2.70/$450` + đúng 2 check ✗ doctor bắt sáng nay, Captures 79 dòng thật, search 8 hit. Event-driven visuals (lỗi/flash/🔒): logic phủ vitest, chờ sự kiện thật để mắt thường xác nhận (fleet đang khỏe — 0 bubble lỗi là ĐÚNG).

## Vấp & học được

- Review bắt **M1 đắt giá**: bật visual lỗi làm lộ bug backend cũ vô hại trước đây — event `failed` không mang `attempt_id` nên guard zombie FE bất lực → false alarm đúng chỗ CEO tin nhất. Nâng cấp UI có thể BIẾN bug im lặng thành bug ồn ào; review adversarial sau UI-change phải soi cả producer phía backend.
- Mesh WebGL không automation được qua a11y snapshot (không ref) — UAT 3D click cần mắt người; label/bubble HTML overlay thì soi DOM được.
- 2 hook chồng nhau (privacy-block *.env, scout-block dist/node_modules) + cwd dính giữa lệnh — tránh được vì đã thuộc từ v51.

## UAT E2E round 2 (LLM thật) + fix vận hành launchd-PATH

CEO soi: task UAT $0 fail-closed ở routing gate TRƯỚC khi gọi LLM (needs_shell + agent không sandbox) → không chạm model. Giao thêm 2 task text-only qua browser: slogan (phan-tich, 1 bước, **native $0.0034 in834/out357**) + giới thiệu+soát chéo (noi-dung→kiem-dinh, 2 bước) → **verdict THẬT `passed 5/5 fail=0`** hiển thị live "✓ đạt" trên desk column. Report `uat-260718-1639-*`.

Lỗi vận hành THẬT lộ ra: worker/MCP/watcher spawn dưới launchd không thấy `node`/`docker`/`gh`/`gws` (launchd PATH tối giản) → deep_agent fail, watcher jira "146 consecutive: node not found", health strip ✗ 6 mục. **Vá**: 2 plist khai `EnvironmentVariables/PATH` qua placeholder `__BIN_PATH__`; install.sh render từ dir THẬT của uv/node/npm/docker/gh/gws (dedup) + 2 prefix Homebrew + default. Verified: health 5→9/11 ✓ (Docker/Slack/gh/gws/MCP lật ✓; chỉ web-search-key + SMTP còn ✗ vì thật sự thiếu key); coordinator process env mang `/opt/homebrew/bin`; hết node-not-found.

**Bài học: fix rename src→my_crew (v51) template hóa uv-path nhưng BỎ SÓT PATH runtime cho binary con — launchd job cần cả EnvironmentVariables/PATH, không chỉ absolute ProgramArguments.**

## Còn treo

- Verdict flash 3s trên ring 3D: data verdict đã live thật; hiệu ứng animation cần mắt người (WebGL headless limit).
- M2 sweep: nếu audit log phình to, cân nhắc sweep theo ticker thay vì theo request (đã throttle 30s — đủ cho hiện tại).
