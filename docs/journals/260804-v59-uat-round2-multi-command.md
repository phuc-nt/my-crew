# v59 — UAT vòng 2 thư ký + multi-command trong một tin
2026-08-04 · hoàn thành

## Làm gì

- UAT vòng 2 với 7 pattern đối kháng trên stack thật (LLM thật, Telegram thật,
  Gmail/Calendar thật): từ chối đúng lệnh chưa hỗ trợ (dời/xoá lịch), Lớp A chặn
  secret trong body mail, tiếng Anh vẫn tạo lịch, recall briefing từ memory/kioku.
- `gui_email` nhận nhiều người nhận: schema `to` thành danh sách comma-separated
  (gws `+send --to` vốn hỗ trợ), build_args chuẩn hoá khoảng trắng.
- Multi-command: một tin nhắn chạy tối đa 3 lệnh theo thứ tự — classifier trả
  list, mỗi lệnh đi đủ đường validate → build_args → gateway độc lập
  (`my_crew/agent/chat_command.py`), lệnh hỏng không hủy lệnh khác, reply từng dòng.
- Vá H1 sót: 5 chỗ `pack.allowlist or None` (telegram_inbox, inbox, task_runner,
  admin/hr graphs) + test pin cấm pattern trên toàn source.

## Quyết định & vì sao

| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Cap 3 lệnh/tin | Chống tin dài bơm chuỗi hành động | Tin >3 lệnh bị cắt, có dòng báo |
| Marker lệnh sau là `chat-command#i ts=…` | Marker cũ không được là substring — guard re-poll lệnh 0 không khớp nhầm approval lệnh 1; tin 1 lệnh byte-identical | Hai định dạng marker song song |
| Pin `or None` bằng test quét source | Vá điểm lẻ đã sót 2 lần (v57 vá 2 chỗ, còn 5) | Test đọc file thô, hơi thô bạo |

## Vấp & học được

- Allowlist rỗng của personal-pack bị `or None` hồi sinh allowlist core NGAY trên
  đường chat Telegram thật — lỗ đúng loại review đã bắt (H1) nhưng chỉ vá nơi
  review chỉ ra. Bài học: vá theo *pattern* (grep toàn repo) chứ không theo *điểm*.
- CI đỏ 3 push liền không ai để ý: test build argv của `gui_email` gọi
  `shutil.which("gws")` thật — runner không có gws. Test build-shape phải stub
  tooling máy, và phải nhìn CI sau mỗi push.
- Trả lời QA nhắc event test đã bị xoá ngoài band (xoá bằng gws tay, thư ký không
  biết) — đặc tính memory, không phải bug, nhưng đáng nhớ khi đọc kết quả UAT.

## Mở / sang sau

- Go-live pilot sales-pm (guarded, cap $10) vẫn chờ CEO gật — checklist sẵn ở
  `docs/go-live-checklist.md`.
