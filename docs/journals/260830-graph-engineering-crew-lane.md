# Graph-engineering crew lane — boundary, fold, gate trượt
2026-08-30 · ✅ Done (plan `plans/260830-0750-graph-engineering-crew-lane/`)

## Làm gì
- `TeamStepPlan.boundary` (5 loại `BOUNDARY_KINDS`, `agent/task_decomposition.py`) — decompose
  phải KHAI vì sao mỗi bước xứng là node riêng; observational-only, phân bố vào
  `route_json.signals.boundary_counts`.
- `fold_unjustified_steps` — gộp bước đúng-1-dep + cùng người + cùng quyền SAU fanout;
  suy từ cấu trúc DAG, bỏ qua nhãn khai; fail-open; sprint path 0 diff.
- `runtime/deterministic_step_check.py` — code đo phủ thực thể + đếm mục trước LLM checker;
  gap code-found fail ngay confidence 1.0; sprint tắt qua `deterministic_precheck=False`.
- Bench vòng 6 (lanes14): 11 cặp material_transform + 1 đề chuỗi, judge mù 3 phiếu/cặp,
  gate trao quyền routing định trước → **trượt**, routing giữ nguyên.

## Quyết định & vì sao
| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Nhãn boundary không có quyền quyết, fold suy từ cấu trúc thuần | Model bịa nhãn để giữ bước sẽ không được gì | Mất khả năng dùng nhãn làm tín hiệu routing ngay |
| Gate định trước, thấy số xấu không chỉnh | "Đo trước trao quyền sau" — tránh post-hoc tuning | Chữ ký material_transform (2 win 3-0 ở lanes11/12) bị bác khi thử 7 biến thể |
| Sprint tắt tiền kiểm định lượng | `coverage_gaps` của sprint biết "nguồn từ chối" không phải gap đóng được | Hai tầng kiểm gần trùng nhau tồn tại song song |
| Trượt gate ⇒ không sửa `classify_brief` | Lưới fold/downgrade/dead-end đã thi hành "crew chỉ nhận task phù hợp" bằng cấu trúc | Chiều mở rộng lên team chỉ còn tiền tố CEO + refusal cứng |

## Vấp & học được
- Chữ ký thắng judge ở n=2 không tổng quát hoá: 7 biến thể cùng chữ ký → team chỉ thắng
  3/7; case A/B-số-liệu tưởng thuần phân tích thua 0-3.
- Fold đổi cả kinh tế lane: team-sau-fold 1.19× cost sprint (trước 3–4×), case fold→1 bước
  rẻ hơn cả sprint vì sprint effort=low vẫn đốt 3 review + 2 rework.
- Salvage hạ nguồn verified nhờ cái chết ORGANIC (ab_test team: 2 drop → terminal dùng nháp
  có dán nhãn 'chưa qua soát') — đề chuỗi dàn dựng lại chạy sạch cả 3 bước ở cả hai lane.
- Lưới `sprint_dead_end` bắn live 2 lần (churn, feedback) tự leo team giữa phiên — phễu 6
  lớp hoạt động đúng thiết kế không cần can thiệp.

## Mở / sang sau
- `route_stats` đọc `boundary_counts` + `material_transform` trên route thật; chạy lại gate
  khi mẫu live đủ dày.
- churn_cohort hỏng CẢ HAI lane — giữ làm canary đề-khó-thật.
