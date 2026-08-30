# Zalo business fleet P2/P3/P4/P6 — và hai lỗi chỉ model thật mới lộ
2026-08-30 · ✅ Done · tag v0.15.0

## Làm gì

- **Control-plane API** (`P2`): `delegate_work` + status hợp nhất + fleet overview cho caller
  ngoài SPA (script/CLI). Confirm bắt buộc mang plan hash hiện hành — hash cũ hoặc thiếu thì
  từ chối, không hành động trên kế hoạch caller chưa nhìn thấy.
- **Escalation → manager agent** (`P3`): việc vượt thẩm quyền mint task 1 bước cho manager thay
  vì chết tại chỗ, chủ được báo kèm nguồn. 3 chốt chống bão: task escalate không escalate lại,
  cap ngày theo nguồn, manager không giao được → degrade báo thẳng chủ. `company.yaml` thêm
  `manager_id` + `escalation_daily_cap`.
- **Credential store mã hoá** (`P4`): `credentials.enc` Fernet per-account thay token plaintext;
  master key do chính store ghi lần đầu; bộ lọc egress học cả hai dạng Fernet (blob lẫn key).
- **Worker packs accounting + Meta Ads** (`P6`) đọc-insight, kèm template profile; agent có media
  dir **bền** (sweep không đụng) tách khỏi tmp dir dùng-một-lần.
- **Live fullflow 33 case** vs model thật: $0.19, 19 phút, không case nào quá 1/4 trần chi phí.

P1 (kênh Zalo) + P5 (digital-assistant khách) **hoãn** — chờ Zalo OA đăng ký + verified.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Sửa ở prompt + mô tả lệnh, **không nới assert** | Hai case trượt là lỗi sản phẩm thật, không phải test khó tính | Phải đo lại toàn ma trận (42/42) trước khi tin là hết |
| Assert live đi vào **bất biến hệ thống**, không vào chữ model viết | Assert "kế hoạch phải nhắc tên Dropbox/OneDrive" trượt lặp lại — mà `_CONTEXT_HEADER` **chủ động dặn** đừng đi lại hướng đã chết, nên kế hoạch trung tính mới là ĐÚNG | Assert yếu hơn về mặt nội dung; bù bằng chỗ đo chắc: đề bài việc mới có mang bản nháp dở dang không |
| `dead_end` thành cờ riêng, không đè `source` | Nó đang phá đúng thứ escalation cần để nói việc từ đâu tới | Thêm 1 field vào route stats + bench metrics |
| Master key vẫn nằm `.env` | Ngang posture hiện tại, không tệ hơn; per-agent .env đầy đủ là YAGNI trên cùng host | Ghi rõ trong threat model, không giả vờ đã giải quyết |

## Vấp & học được

- **Hỏi giá/tỷ giá được trả lời từ trí nhớ cũ, không tạo việc nào.** Chỉ lộ khi chạy model thật —
  stub không có "trí nhớ" để mà trả lời sai. Bài học: câu hỏi mà đáp án **đổi theo thời gian** là
  một việc tra cứu, không phải câu hỏi.
- **Catalog to hơn làm phân loại tệ đi.** Việc đụng bên ngoài (gửi mail, clone repo chạy test) trả
  về danh sách lệnh thay vì thành việc — admin trượt **4/5**, personal **1/5**. Đo trước rồi mới
  sửa, nên bản vá nhắm đúng gốc: catalog lớn cho model thêm cớ kết luận "không lệnh nào khớp".
- **Ba loại thất bại phải tách bằng cách chạy lại, không bằng suy đoán.** Một case A1 còn trượt
  1/3 → chạy đơn lẻ 8 lần: 8/8 đúng. Là nhiễu ~1/11, không phải bug chưa sửa xong.
- **Bench trả về rỗng phải kiểm chứng trước khi mừng.** `compare_reports` cho `[]`; tiêm một đột
  biến giả (`llm_calls` 1→100) thấy nó bắt được → rỗng đúng là 0 delta thật.

## Mở / sang sau

- P1 (Zalo OA) + P5 — chờ OA verified; vế acceptance "gửi Zalo chạy bình thường" của P4 hoãn theo.
- `escalation_daily_cap` nên per-source hay global; `ads_credential` nối vào config builder.
- `deepagents` chưa cài trong venv → 1 test community-loop fail sẵn từ trước, ngoài phạm vi vòng này.
