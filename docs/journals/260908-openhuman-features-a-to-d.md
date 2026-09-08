# Tính năng mượn openhuman gói A→D — duyệt trước thành policy, boundary, drawer, walkthrough
2026-09-08 · ✅ Done

## Làm gì
- **A — workroom chat**: preview kế hoạch mang `manifest` (bước + cờ external/shell/web/mail/
  review, đọc từ draft đã lưu) → thẻ duyệt trước; confirm nhận `preauth_scope` `once|always`,
  cột mới `team_tasks.preauth_scope`; ticker tự duyệt gate Lớp B nhân danh CEO, scope `always`
  học action thật thành luật ALWAYS ở store của đúng agent (`created_by ceo:preauth`); DENY đã
  học và `require_ceo_approval` vẫn thắng. Web: hàng đợi follow-up, dải todo từ artifact index,
  ghi chú "vì sao / làm gì tiếp" cho bước hỏng / hành động bị chặn / việc kẹt.
- **B**: dải control-plane trên `/work` (4 số + đèn điều phối, SSE invalidate), error boundary
  theo route, `/health` trả `version` + banner "có bản mới" (poll 60 s, chỉ gợi ý tải lại).
- **C**: gập `step_activity` thành một dòng "Hoạt động nền", thẻ câu trả lời dở (nháp + lỗi +
  guide + thử lại; artifact API thêm `status`/`error`), chip nguồn trích theo host.
- **D**: walkthrough 4 bước neo vào phần tử thật (nhớ `localStorage`, replay từ bảng ⌨), thẻ
  chào theo hub với 3 brief mẫu seed composer, cột chat kéo được (chuột + phím, nhớ độ rộng),
  bảng lệnh ưu tiên hàng "Ở đây", chuông có "Nhắc lại sau 1 giờ / 1 ngày".
- Cổng: BE 4848 pass / 1 skip · ruff · vitest 505 (78 file) · Playwright 64/64 · tsc · oxlint
  · bundle dựng lại · tự test trình duyệt trên server thật (home tạm, không đụng `.data`):
  12 ảnh chụp, 0 lỗi console/page/5xx. Live suite (`-m live`, 69 ca): 65 xanh / 4 đỏ trong 2:30:00 — cả 4 đỏ đều không thuộc A→D (1 timeout hạ tầng, 3 biến thiên model: planner không đặt `needs_mail`, effort chấm `medium` thay vì `high`, câu nhận xét THIẾU có chứa số ngày). Ca live preauth mới của gói A xanh.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Manifest đọc từ draft đã lưu, không từ preview text | Thẻ và run phải không thể lệch nhau; text là thứ model viết | Preview thêm một lượt đọc store |
| `preauth_scope` ghi SAU confirm thành công, không vào `plan_hash` | Draft cũ không được mang policy; đổi scope không làm hash lệch | Hai lần ghi store trong một confirm |
| Nhánh preauth chạy SAU khối luật đã học, tôn trọng `require_ceo_approval` | "Duyệt tất cả" là quyền mở, không phải quyền ghi đè rào an toàn CEO từng đặt | Task có DENY sẵn vẫn hỏi dù đã duyệt tất cả — đúng ý |
| Học luật `always` từ action THẬT trong hàng đợi, ở store của agent bước đó | Luật theo key action nên phải là action đã thành hình; học ở store chung sẽ rò sang agent khác | Task chưa tới gate thì chưa học — policy chỉ hình thành khi có hành động |
| `/health` đăng ký trong `create_app` trước catch-all | Route module-level sau catch-all trả `index.html`, TestClient không thấy | Test soi nguồn cũ phải viết lại thành test HTTP |
| Banner chỉ gợi ý tải lại, không tự reload | Tự reload giữa lúc CEO đang gõ brief là mất dữ liệu | Bản cũ có thể chạy tiếp tới khi người dùng bấm |
| e2e mock tự cắm cờ walkthrough-done | 64 test cũ không được đổi hành vi vì một thẻ mới | Test walkthrough phải opt-in `walkthrough: true` |
| Snooze lưu tách khỏi dismiss, kèm fingerprint | Hai nghĩa khác nhau; cảnh báo đổi nội dung phải thức dậy sớm | Thêm một key localStorage và một timer |

## Vấp & học được
- `/health` từng nằm SAU catch-all SPA trên `app` module-level → trả HTML; test cũ "đọc
  nguồn hàm" che mất bug này. Test contract phải đi qua HTTP.
- `useState(initial)` không chạy lại khi `/team` → `/team?hire=1` giữ nguyên mount → panel
  tuyển không mở; cần `useEffect` theo query.
- scout-block hook chặn cả lệnh khi `.venv` ghép với lệnh khác, và chặn từ `target`/`PORT`
  cả trong nội dung heredoc → script/server phải ghi bằng Write tool rồi `zsh <path>`.
- zsh: glob `--include=*.ts` không khớp là hủy cả lệnh compound.

## Mở / sang sau
- Thẻ duyệt trước mới phủ gate Lớp B; bước `needs_review` vẫn đi qua vòng self-check như cũ.
- Chuông chưa có "xem lại mục đã bỏ qua / tạm ẩn"; mới chỉ có dòng đếm.
- Ý openhuman chưa mượn (cố ý): flows DAG canvas, mascot/voice, rewards, feedback voting,
  billing, memory graph.
