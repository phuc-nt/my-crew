# Fast/crew lane routing v2 — live suite, benchmark v2, và cái gate chưa từng tồn tại
2026-08-26 · ✅ Phase 4-6 done (khép plan 6 phase)

## Làm gì

- **Live fullflow suite** (`tests/fullflow_live/`, 18 case): chạy end-to-end với model thật, assert trên **route record** (`route_json` + hình dạng DAG) chứ không phải prose — thứ duy nhất ổn định qua model nondeterminism. Opt-in bằng `-m live`; `addopts = ["-m", "not live"]` để `pytest` trần không bao giờ tiêu tiền.
- **Đếm đầu việc đánh số giữa câu**: cùng ba việc, viết xuống dòng thì ra team, viết liền một câu thì ra sprint — quyết định phụ thuộc CEO có bấm Enter hay không, mà đó không phải tính chất công việc. Nay hai cách viết đếm như nhau.
- **Lane stats** đo 3 miss-rate (`dead_end`/`downgrade`/`upgrade`) **trên `routed_tasks`**, task trước v77 không có route record vào lane `unknown` thay vì pha loãng mẫu số.
- **Benchmark v2, 4 mode**: `routing`/`release` (0 lượt gọi model, so hai bản), `tasks` (đọc store thật), `judge` (chấm mù A/B). Hai mode so sánh từ chối diff hai báo cáo khác `format_version`.
- 3 commit: `fix(ops)` (2 lỗi live bắt) · `feat(bench)` · `docs`. Cổng cuối: 3991 BE passed, 1 skipped, 18 live deselected, ruff sạch.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Live suite opt-in bằng `addopts`, không chỉ `skipif` | `skipif` chỉ chặn máy KHÔNG có key — tức bảo vệ CI chứ không bảo vệ máy lập trình viên đã cấu hình key | Phải nhớ `-m live`, dễ tưởng suite không tồn tại |
| Chỉ số phải có ngoặc (`(1)`, `[1]`, `1)`), loại `1.` trần giữa câu | Giữa câu tiếng Việt `1.` gần như luôn là số thứ tự của DANH TỪ — "Điều 1. Điều 2." — chứ không phải đầu việc | `1.` đầu dòng vẫn tính, nhưng nhờ neo đầu dòng của `_ASK_LINE_RE`, không phải nhờ hàm này |
| Dò dãy liên tiếp ở BẤT KỲ đâu, không bắt buộc từ phần tử đầu | Một con số lạ đứng trước ("Ngân sách 5. 000 rồi 1) a 2) b") không được phép tắt luôn khả năng phát hiện | Quét O(n²) trên danh sách chỉ số — n nhỏ nên không đáng kể |
| Judge luân phiên vị trí tất định, bỏ random | Đo trên 2000 seed: ~24% số lần cả ba phiếu cùng một thứ tự — đúng lúc "bias tự triệt tiêu" là sai | Mất tính độc lập giữa các phiếu, đổi lấy cân bằng đảm bảo |
| Giữ tham số `rng` trong chữ ký `judge_case` dù đã vô dụng | 7 test đang gọi; phá contract chỉ để dọn một tham số là không đáng | `del rng` trông lạ, phải có comment giải thích |

## Vấp & học được

- **Cái gate an toàn chưa từng chạy**: `pytestmark` đặt trong `conftest.py` bị pytest **bỏ qua hoàn toàn** — không lỗi, không cảnh báo. Đo thật: `-m live` chọn ra **0/18** case. Nghĩa là máy không key sẽ ĐỎ vì lỗi xác thực thay vì skip, còn máy có key thì `pytest` trần tiêu tiền thật. Cả phase không ai thấy vì tài liệu mô tả cái gate *lẽ ra phải có*, còn mọi lần chạy đều né thư mục bằng `--ignore` thủ công. Bài học: **tài liệu mô tả cơ chế không phải bằng chứng cơ chế chạy** — phải đo cả chiều dương lẫn chiều âm.
- **Docs agent bịa rất trôi chảy**: subagent viết docs (Haiku) tự báo "đã verify mọi tên hàm với code"; đối chiếu thì **5 khẳng định sai**, trong đó 3 cái *đảo ngược* quyết định thiết kế có thật — nói `upgrade` dùng lại `routed_task_id` (thật ra cố ý dựng task MỚI vì kế hoạch sprint là DAG đã chốt hash) và nói nháp sprint làm "starting point" (thật ra cố ý chỉ làm THAM KHẢO). Văn phong khớp hoàn hảo với docs viết tay xung quanh. Bài học: **phần kém tin cậy nhất của output một agent là lời nó tự khai đã kiểm chứng**.
- **Tỉ lệ đo trên mẫu số sai thì càng chạy càng đẹp**: miss-rate chia cho TẤT CẢ task khiến lịch sử store càng dài thì tỉ lệ càng loãng — một chỉ số tự cải thiện theo thời gian mà không cần ai sửa gì.
- **Test cũ sai thì sửa test, nhưng phải nói rõ vì sao**: sau khi sửa mẫu số, `test_..._over_all_tasks` đỏ. Đổi tên + cập nhật thay vì revert fix, vì test hàng xóm của nó đã khẳng định sẵn task legacy không được gộp vào — tiền đề của test cũ mới là cái lỗi thời.

## Mở / sang sau

- `route["effort_high"]` hiện **không có chỗ nào trong runtime đọc lại** (chỉ test đọc) — cờ để đo, chờ dữ liệu thật trước khi cho effort quyền đổi lane.
- Còn một warning nondeterministic ở đuôi full-suite, không dựng lại được qua 3 lần chạy và không xuất hiện dưới bộ lọc warning; không do đợt thay đổi này.
- v0.14.0 vẫn chưa tag (bản phát hành cuối là v0.13.0) — tag + publish PyPI là quyết định của CEO.
