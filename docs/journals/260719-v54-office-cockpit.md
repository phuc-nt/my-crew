# v54 — Văn phòng cockpit: rail hành động, feed ra-ngoài, lịch trực, review chi tiết

**Ngày:** 2026-07-19 · **Commits:** 9 (P1 BE → P2 rail → P3 feed/tray/cost → P4 3D → P4b criteria → 3 UAT-fix + ✋ coordinator) · **Suite:** 2389 BE + 261 FE · **Plan:** `plans/260719-1423-v54-office-cockpit-redesign/`

## Bối cảnh & quyết định

Brainstorm gap-analysis: backend build nhiều hơn Văn phòng thể hiện (approvals/clarify vô hình, review chỉ flash 3s, hành động gateway ra thế giới thật không thấy, fan-out/deep_team vô hình, không lịch trực, cost ẩn). CEO chốt 5 quyết định: **cockpit-first** (Văn phòng là nơi LÀM, không chỉ xem), duyệt/clarify **tại chỗ**, 3D **chọn lọc rẻ-mà-đắt**, thêm cả 4 hạng mục, **layout A rail-trái** (chọn giữa 3 mockup ASCII). Giữa chừng CEO duyệt thêm scope: **persist criteria review vào captures** (P3 phát hiện per-criterion tính xong bị vứt — không tự chế endpoint, dừng hỏi đúng quy tắc).

## Đã làm

- **P1 BE (3 miếng nhỏ):** bridge `external_action` tại choke point `_record` gateway (try/except-total, no-content-echo — chỉ tool + target ngắn); `GET /api/schedule/upcoming` (croniter); cờ `deep_team` vào step event. 13 test (fail-safe, audit byte-identical).
- **P2 rail:** grid 3 vùng `[260px | 1fr | 300px]`; khay "Chờ anh/chị" gộp approvals + clarify fleet-wide, xử lý TẠI office qua đúng API sẵn (`api.approve/reject` + shared context, `api.answerClarify`); "Sắp chạy" 60s.
- **P3 giữa-phải:** filter [Tất cả|Bước|Ra ngoài]; tray review; cost chip lazy per-room. Phát hiện criteria bị vứt → escalate CEO.
- **P4 3D:** ✋/×N/ghost — toàn bộ logic vào `agent-office-state` pure (unit-test đủ nhánh), component chỉ render props.
- **P4b:** cột `criteria_json` captures (guarded ALTER kiểu v46), chỉ expose ở detail endpoint; tray correlation reviewer+counts+verdict đúng-1-khớp mới render, mơ hồ → EmptyState.
- **P5 UAT live 6/6** (fleet + LLM + kết nối thật): clarify trả lời tại rail (3→2 server), tray hiện criteria THẬT từ review LLM thật, 2098 external_action trong store, **vòng cockpit tự khép** (task stalled → escalation đẻ clarify → hiện ở rail → CEO xử tại chỗ).

## 3 bug thật UAT bắt (fix trong phiên)

1. **Schedule rỗng trên fleet đang chạy watch**: endpoint đọc `schedule:` thô — service TIÊM pseudo-kind (`watch */5`, team-tick) lúc runtime → dùng `_effective_schedule` + lọc heartbeat.
2. **480px tràn 2600px**: grid collapse `1fr` trần — 1 câu clarify dài đẩy min-content → `minmax(0,1fr)` + `min-width:0` mọi zone.
3. **Dòng external đúp**: chip author đã hiện actor, tool id (`telegram:<chat>`) nhúng sẵn target → formatter bỏ actor + dedupe detail.

Thêm: ✋ không hiện cho clarify của coordinator (P4 chỉ gắn agent-desk; `agent_id="coordinator"` không có bàn) → pending không-có-bàn dồn về bàn tròn.

## Vấp & học được

- **Nút re-render giữa snapshot và click** (agent-browser ref-stale): click báo Done nhưng rơi hư không — 2 confirm "thành công" giả, 3 draft mồ côi. Nghiệm: verify STATE (DB/server) sau mỗi hành động automation, đừng tin CLI "Done"; flow nhiều bước dùng API python E2E làm chuẩn đối chiếu.
- **Preview assign gọi LLM** (~10-30s) — automation phải chờ điều kiện (`until … Xác nhận`), không sleep cố định.
- Log launchd tách nhiều file (`web.log` access ≠ `web.err.log`) — grep đúng file trước khi kết luận "request không tới".
- Fail-closed v45 chặn bước Slack bị LLM gắn nhầm `needs_shell` → task stalled → nhưng chính vòng escalation biến nó thành clarify ở rail: moat + cockpit phối nhau đúng thiết kế.
- drei Html overlay không mount trong headless agent-browser (labels=0) — probe DOM 3D cần headed; logic dồn vào pure state để test không phụ thuộc render.

## Còn treo

- Follow-up (ghi trong report P4b): opaque attempt_id trên review event → join tray chính xác tuyệt đối (hiện fail-safe đúng-1-khớp).
- ✋/×N/ghost cần mắt CEO xác nhận trên browser thật (Html overlay không capture được máy này).
- Screenshot guide cập nhật đợt sau; 9 commit chưa push — chờ CEO quyết release.
