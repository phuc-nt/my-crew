# Template nhân sự: skill đúng vai + phủ live theo nghiệp vụ

2026-09-08 · ✅ Done

## Làm gì

- Mở kênh `skills` cho template (contract v2): `template.yaml` khai tên skill pack →
  loader trả về → `_spec_from_template` chuyển tiếp → `agent_create` xác thực từng tên
  với `load_skills(domain=…)` rồi ghi vào profile, nên `load_skill_pool` nạp được. Gắn
  5 skill pm cho pm-coordinator, `read-meta-ads-insights` cho ads,
  `read-accounting-ledger` cho accountant; thêm skill riêng cho analyst/content/qa.
- Sửa role hint: `role_hint_from_soul` bỏ qua dòng heading nên vai không còn hiện ra
  là chữ "SOUL" trong roster của planner.
- Bộ live mới `tests/fullflow_live/test_live_template_roles.py`: R1 dựng đội office từ
  template rồi giao brief cần web (bước `needs_web` phải về researcher, bài nộp phải có
  URL, bước review phải về qa), R2 soi `skill_usage.json` chứng minh skill template nạp
  và được selector chọn trong lần chạy thật, R3 briefing của trợ lý cá nhân ở chế độ khô.
- Selector skill có sàn đỡ: selector trả rỗng thì các skill khai `applies_to` đúng loại
  việc đứng thay; lời nhắc chọn skill nói "loại công việc" thay vì "báo cáo PM".
- SPA hiện chip "kỹ năng: …" trên thẻ template để người thuê thấy trước khi bấm.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| `applies_to` chỉ đỡ khi selector im lặng, không phải lọc cứng | Mô hình reasoning có lần trả nội dung rỗng (chỉ có reasoning token) ⇒ bước mất sạch skill viết riêng cho nó. Nhưng khi selector đã trả lời thì câu trả lời là chuẩn, không nới theo `applies_to` | Một lần selector im lặng có thể nạp nhiều skill hơn mức cần |
| Ghép artifact qua `outcome_ref` chứ không đoán tên file | Artifact đặt tên theo thứ tự hàng (`step-<n>.json`), không theo `step_id`; join theo tên bước là sai từ gốc dù test vẫn xanh nhờ may | Test phải mở store thay vì chỉ đọc HTTP |
| Brief live ghi số lượng ở dạng cận dưới, không nhắc QA | Self-check sinh tiêu chí nghiệm thu ngay từ brief: "đúng 2 nguồn" biến bài 5 nguồn thành trượt, "QA đã soát" biến việc của lane thành tiêu chí | Brief bớt tự nhiên hơn lời người thật |

## Vấp & học được

- R1 đỏ hai vòng vì đọc sai hình dạng payload: trạng thái task nằm ở
  `final["state"]["status"]`, harness đọc `final["status"]` nên luôn thấy `None` — và
  cùng lỗi đó khiến `note_cost` nhận `None` nên journey không vào bảng baseline. Store
  nói `done`, HTTP cũng nói `done`; chỉ có test là nói khác.
- Sprint lane luôn gắn `needs_review`, nên nhắc "nhớ cho QA soát" trong brief chỉ tạo
  thêm một tiêu chí nghiệm thu để trượt, không tạo thêm bước review nào.
- Ca live đắt tiền chỉ trả lời được câu hỏi nó hỏi đúng: hai vòng đầu tốn ~11 phút mỗi
  vòng để phát hiện lỗi đọc key, thứ mà một lần đọc payload thật đã lộ ra.
- Vòng live đầy đủ (66 xanh / 6 đỏ) bắt được lỗi không thuộc phạm vi vòng: bản tin ads
  báo "THIẾU" nhưng vẫn kèm ngày, và với chủ doanh nghiệp thì mọi con số trong một bản
  không có số liệu đều bị đọc là số liệu. Cấm chữ số không đủ — phải giấu luôn ngày,
  vì model nhìn thấy ngày là viết lại ngày.
- Ba ca đỏ còn lại đỏ vì đồng hồ của test, không vì sản phẩm: hằng số 180 s/300 s đứng im
  nhiều tháng rồi hỏng khi upstream chậm, trong lúc client vẫn còn hạn 240 s để tự thử
  lại. Test hết giờ trước cơ chế phục hồi thì nó đo đồng hồ chứ không đo hành vi.

## Mở / sang sau

- pm-coordinator chưa có ca live vì cần Jira thật; mới phủ bằng test offline.
- Brief hiện bị heuristic đẩy vào sprint lane nên vai content trong đội office chưa
  được dùng tới trong R1.
