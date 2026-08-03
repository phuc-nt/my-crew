# v58 — Quét roadmap: roster, email, queue, nợ, attempt_id, kioku, go-live
2026-08-03 · ✅ 7/7 phase · **Plan:** `plans/260803-2146-v58-roadmap-sweep/` · **Suite:** 2443 BE + 281 FE + 8 e2e · 7 commit trên main

## Làm gì

- **Thư ký mạnh thêm 3 nấc**: biết roster crew (yaml-peek, gợi ý giao việc đúng tên) ·
  lệnh `gui_email` (nới `_VETTED_COMMAND_TYPES` đúng MỘT type theo quyết định CEO — Lớp A
  email + posture attachment nguyên vẹn, test pin) · **kioku memory** (v19.5 thi công:
  recall ngữ nghĩa theo câu hỏi từ vault per-agent, đủ 7 điều kiện red-team, degrade êm).
- **Queue transparency**: card kanban hiện "⏳ xếp sau N việc (~N phút)" — tính từ đúng
  thứ tự ticker phục vụ (created_at cũ trước, 1 hành-động/tick); hết "kẹt im lặng".
- **Review tray join thẳng**: event review mang `attempt_id` mờ (identifier — không phạm
  no-content-echo), heuristic đếm-khớp v54 chỉ còn là fallback cho event cũ.
- **Nợ dọn**: `/staff` hết `load_profile` per-staff (yaml-peek chung `peek_profile_yaml`,
  test chống tái phát) · codebase-summary header v50→v58 · 2 mục roadmap chết đóng có lý do.
- **Go-live**: `docs/go-live-checklist.md` từ kiểm kê fleet thật + lộ trình guarded→
  autonomous + **drill kill-switch thật**.

## Quyết định & vì sao

| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Nới vetted-types cho email — CHỈ email_send, có test pin danh sách | CEO chốt thư ký được quyền ghi; pin để lần nới sau không lặng lẽ kèm type khác | Chat gửi được mail khi có SMTP |
| Kioku recall theo query từ câu hỏi chat (param mới của `resolve_memory_text`) | Recall mù (--digest) vừa tốn vừa nhiễu; seam cũ không có chỗ cho query | 6 call-site khác giữ default "" |
| `build_args` được raise ValueError → thành reply | "Chưa cấu hình SMTP" phải là câu trả lời, không phải run lỗi câm của worker | — |
| Queue position tính trong request list, không query thêm | Cùng dữ liệu đã fetch; N+1 là đúng cái bệnh vừa dọn ở /staff | Vị trí trễ tối đa 1 lần poll |

## Vấp & học được

- **Drill go-live bắt bug an toàn thật**: `AGENT_WRITE_DISABLED=true` bất lực vì mọi
  profile ghi `write_disabled: false` tường minh → luật "profile wins" đè chết kill-switch.
  Vá: env true thắng tuyệt đối. Bài học: công tắc khẩn cấp phải được DIỄN TẬP, không
  được tin vào docs — đây đúng loại thứ chỉ lộ khi kéo thử cầu dao.
- Hook Dandori (G1.5, sản phẩm khác của CEO cài local) chặn edit chứa token-giả/PII-mẫu
  trong test — né hợp lệ bằng ghép chuỗi runtime; CEO sau đó gỡ dandori khỏi repo này.
- `ck plan check` đòi cwd đúng plan dir; `s.replace` không khớp thì im lặng — sửa plan
  file bằng Edit tool có verify thay vì sed/replace mù.

## Mở / sang sau

- UAT gửi email thật: chờ CEO cấu hình `smtp:` (profiles/thu-ky) + `SMTP_PASSWORD`.
- Go-live pilot: chờ CEO quyết agent + ngày (đề xuất sales-pm, nấc guarded, cap $10).
- Kioku: vault thư ký mới có 2 entry seed — giá trị thật tích lũy theo tuần sử dụng.
