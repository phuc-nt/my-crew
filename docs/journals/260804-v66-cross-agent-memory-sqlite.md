# v66 — Cross-agent memory SQLite-first (trí nhớ chung cho cả đội)
2026-08-04 · hoàn thành

## Làm gì

- Scout đổi cỡ bài toán: máy móc đã có từ v2-era (remember node sau report + team-step;
  sibling read theo `project_group`, cap 40, chỉ prompt nội bộ) — chỉ thiếu: backend
  bền, group, và 2 dây chưa cắm.
- **Backend `store: sqlite`** (default MỚI thay in-memory): 1 file chung
  `.data/memory_store.sqlite3` (SqliteStore của langgraph, WAL + busy_timeout,
  `isolation_level=None` vì store tự BEGIN); `memory`/`postgres` tường minh giữ nguyên;
  unknown vẫn fallback in-memory (pin cũ).
- **Luật riêng tư thư ký** (CEO chốt): field `memory_share: full|read_only` — secretary
  `read_only`: đọc fact cả đội nhưng fact cá nhân (email/lịch CEO) không bao giờ vào
  prompt agent khác. Group `project: company` cho 8 agent (user-data).
- **Chống injection fact bền**: block sibling qua `format_internal_content` thay vì
  nối thô (fact giờ sống qua ngày = bề mặt second-order lâu dài); retention 90d trong
  `storage_hygiene` (duyệt Store API per-namespace, không SQL thô vào bảng langgraph).
- **Hai dây chưa cắm phát hiện nhờ UAT sống** (unit test không thấy):
  (1) graph team-step compile KHÔNG có `store=` → remember node ghi vào hư không;
  (2) 6 agent office còn `dry_run: true` từ template cũ → remember node tự gate.
  Vá cả hai (compile nhận `memory_store`, flip dry_run — MCP allowlist office vẫn
  default-DENY nên không mở bề mặt ghi ngoài).
- UAT sống chốt: task thật → researcher persist 20 fact vào file chung; coordinator
  đọc 40 fact từ 6 sibling, secretary BỊ LOẠI khỏi nguồn; secretary đọc cả 7 sibling.
  Suite 2525 BE.

## Quyết định & vì sao

| Quyết định | Vì sao | Trade-off |
|---|---|---|
| SQLite chung trước, Postgres để đo sau | Chính đội tự nghiên cứu ra số (~0đ vs ~3,5tr/th); WAL đã chứng minh đa-process ở team_task_store | Concurrent-writer cực đoan sau này mới cần PG |
| read_only cho secretary thay vì tách hẳn | Điều phối cần thư ký BIẾT việc đội; đời tư CEO không cần đội biết | Fact thư ký vẫn nằm file chung (cùng máy) — cách ly ở tầng đọc-prompt |
| Flip dry_run 6 agent office | Đội làm việc thật từ lâu; dry_run=true là template sót, chặn nhầm memory | Posture đổi — bù: allowlist rỗng + Lớp A/B nguyên vẹn |

## Vấp & học được

- "Đã wired" ≠ "có điện": remember node có mặt trong graph hàng tháng nhưng `store=`
  không được truyền lúc compile — mọi fact team-step rơi vào hư không mà không ai thấy
  vì backend mặc định vốn dĩ cũng mất sau mỗi run. Persistence bật lên mới lộ.
- Extractor tách fact theo DÒNG nên bảng markdown thành 20 "fact" vụn — chất lượng
  trích cần một vòng riêng (ghi Mở).

## Mở / sang sau

- Chất lượng extractor: gộp/lọc fact (bảng markdown → 1 fact tổng), có thể kèm dedup
  ngữ nghĩa — đo thêm vài ngày dùng thật rồi quyết.
- Postgres: chỉ khi đo được tranh chấp ghi thật.
