# Project Roadmap — my-project-manager

> Lộ trình + trạng thái. Cập nhật khi mốc đổi. Chi tiết mỗi vòng: `docs/journals/`.
> Cập nhật: 2026-07-11.

## Trạng thái tổng

**Production-usable, single-user. Đã ship tới v19.** ~1730 backend + 177 FE test, ruff/tsc
sạch. Mọi vòng lớn E2E trên browser + LLM + ticker thật.

## Đã hoàn thành (gọn — chi tiết ở journals/plans)

| Mốc | Nội dung |
|---|---|
| **Nền tảng (v1)** | Single-agent PM: 4 báo cáo (daily/weekly/okr/resource) + Action Gateway (Lớp A/B) + đa-audience. |
| **Platform (v2, M1-M2)** | Multi-agent core (registry + worker + isolated store) · LangGraph interrupt/SSE · Web SPA (React) · Postgres+Store opt-in. |
| **Extensibility (M3-M6)** | Skills · cross-agent memory · domain-packs (pm/hr) · MCP suite · company docs. |
| **Trust & ops (v8, v10)** | Trust ladder (auto-approve Lớp B) · multi-project rollup · theme/dual-mode/installer hardening. |
| **Reporting (D4)** | Xuất .xlsx đính email (Lớp B, internal-only). |
| **Agent Office (v12)** | Team-task: coordinator ticker + store + lease · giao việc đội · office room + màn 3D. |
| **Team self-op (v13-v14)** | Soát chéo tự chèn · consult đồng nghiệp · song song cap 2 · full replan · tự cứu bước kẹt · 3D "sống". |
| **PIC & office UX (v15-v17)** | Giao việc @PIC/@all · auto-confirm · màn Văn phòng hợp nhất → workrooms → command-center 3 cột · artifact viewer · coordinator health banner. |
| **Registry user-data (v18)** | registry.yaml thành user-data (hết mất đội) · recovery UI · scheduler seed-at-discovery · 3D theme-aware. |
| **Agent-harness v1 (v19)** | Memory provider seam (static; kioku hoãn v19.5) · workspace protocol v2 (vault/ + skills/ per-agent) · per-agent skill có guard · capability block internal-only. |

## Việc nên làm tiếp (từ UAT + nợ kỹ thuật)

Ưu tiên giảm dần. Nguồn: `plans/260711-0711-.../reports/uat-*findings*.md` + HANDOVER §8.

### Agent-harness (chương trình 3 vòng — brainstorm 260711)
- [x] **v19**: memory seam + static + workspace protocol (vault/skills per-agent) + capability block.
- [ ] **v19.5 (kioku adapter)**: cắm my-kioku sau khi giải 7 điều kiện red-team — dist
  (`bun link`+`MY_KIOKU_BIN`, BỎ `bun x`); recall `<query>` (không `--digest`); wrap digest
  `format_internal_content`; env allowlist subprocess; flock per-vault + stagger reflect;
  health probe thật; pin "zero network I/O". Xem `plans/260711-1543-v19-.../plan.md` §"Giữ cho v19.5".
- [ ] **v20**: channel binding account→agent (mỗi agent 1 bot Telegram, OpenClaw-style).
- [ ] **v21**: 2-mode UI (CEO đơn giản / Maintainer config+monitoring).

### Tài liệu
- [x] Dựng bộ doc chuẩn v18 (overview-pdr, system-architecture, deployment-guide, roadmap).
- [x] Archive doc cũ (v1/v2/interview) + gộp UAT.
- [ ] Đồng bộ header `codebase-summary.md` (ghi v13 → v18) + gộp phần lịch sử dài.

### Sản phẩm
- [ ] **Web-search key cảnh báo → hành động**: agent bật web_search thiếu key mới chỉ
  cảnh báo; cân nhắc auto-tắt flag hoặc nhắc rõ ở luồng giao việc.
- [ ] **Queue transparency**: coordinator 1 hành-động/tick (60s) theo thứ tự cũ→mới →
  task mới chờ vài phút khi hàng đợi đông; UI nên hiện "đang xếp sau N việc".
- [ ] **QA reply persist (tùy chọn)**: câu trả lời "hỏi tiến độ" hiện không lưu — thêm
  kind lưu nếu CEO muốn lịch sử hỏi-đáp.
- [ ] **Chi phí classify/QA vào cost-cap**: hiện chỉ log, chưa tính vào trần chi phí việc.

### Kỹ thuật
- [ ] Focus-trap + hiển thị detail lỗi cho artifact viewer (drawer).
- [ ] Dọn artifact hex mồ côi sau demo (task giao thật trong demo).
- [ ] Cân nhắc gộp/chuẩn hóa các module >200 LOC còn lại (theo rule modularization).

## Ngoài phạm vi hiện tại (cần thiết kế lại nếu mở)

- Multi-user / hosted multi-tenant (auth + isolation phải làm lại).
- RBAC, thanh toán, chạy cloud.

## Nguyên tắc khi thêm tính năng

1. Brainstorm → plan → **red-team plan** → cook → review → **E2E thật** → docs/journal.
2. Field mới trên step → hỏi "có va `_verify_plan_hash` không?" (metadata phải NGOÀI hash).
3. Ghi ra ngoài mới → PHẢI qua Action Gateway.
4. Không phá 6 bất biến (xem HANDOVER §5).
