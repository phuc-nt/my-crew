# v69 — Bề mặt chat cho approval (push · duyệt/từ chối · rule · digest tín hiệu 6)
2026-08-05 · hoàn thành · phát hành 0.8.0

## Làm gì

- **Push khi enqueue** (P1): Lớp B vào hàng đợi → DM Telegram ngay, kèm id + agent + 1
  dòng nhận diện. Đi qua `notify_operator_best_effort` chứ không nối dây từng gateway
  (~20 chỗ dựng `ActionGateway`, nối tay sẽ sót đúng những agent hay queue nhất).
  `approval_summary` chỉ render trường ĐỊNH DANH — người nhận, tên tool, `argv[:3]` —
  không bao giờ subject/body, và gộp newline để giá trị bịa không vẽ được dòng giả.
- **Duyệt/từ chối + rule từ chat** (P2): bề mặt THỨ BA trên cùng đường gateway, không
  phải đường duyệt thứ hai. Cặp `(agent_id, approval_id)` bind ở PREVIEW, không resolve
  lại ở confirm — push chen giữa 2 bước không dời được đích (bài học v64 H1). Rule
  always/deny mô tả bằng LỜI dịch từ binding thật, không phải `params_hash`.
- **Digest tín hiệu 6** (P3): mọi approval pending của mọi agent, không có ngưỡng tuổi —
  draft cũ là CEO tự bỏ, approval treo là agent ĐỨNG IM. Kèm `list_lessons` (v68 ghi
  bài học nhưng chưa ai đọc lại được) và số lần hồi sinh trong `list_team_tasks`.
- Suite kết arc: **2781 BE passed, 9 skipped**, ruff sạch.

## Quyết định & vì sao

| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Lệnh approve/reject chat là **admin-only**, `list_lessons` thì không | Approve thò tay vào store của agent KHÁC → thẩm quyền fleet. Đọc bài học của chính coordinator là câu hỏi giao việc | CEO phải ở chat admin để duyệt, không duyệt được từ chat thư ký |
| Rule mô tả bằng lời, không bằng hash | Đồng ý với 1 digest mù là đồng ý mù. Chỗ nào key không bind gì thì câu chữ nói thẳng "mọi hành động loại này" | Phải giữ 2 chỗ (mô tả + `derive_rule_key`) không lệch — nên `email_domains` promote thành public để dùng chung 1 nguồn |
| Action không summarize được thì TỪ CHỐI rule always/deny | Đồng ý vĩnh viễn dựa trên mô tả stub không phải là đồng ý | Vài action lạ không tạo rule được, phải duyệt tay mãi |
| Approval treo được MIỄN suppression của model | Nới đúng tiền lệ `scratch:` sẵn có, không đẻ cơ chế mới | Model mất quyền cân nhắc với 2 loại key — chấp nhận, vì cả hai đều không phải chuyện phán đoán |
| `approvals.db` chỉ có bảng rule ⇒ `[]`, không raise | Đó là trạng thái HỢP LỆ (`ApprovalRuleStore` tạo cùng file), không phải lỗi | Mất khả năng phân biệt "chưa từng queue" với "schema mất bí ẩn" — đổi lấy việc không giết tín hiệu cả fleet |

## Vấp & học được

- **UAT thật bắt đúng lỗi mà 2778 test xanh không thấy.** Nhịp heartbeat đầu tiên với 1
  approval treo trả `suppressed` — model trả token ack, nuốt đúng tin BẮT BUỘC phải tới.
  Test nào cũng đúng vì test kiểm digest, không kiểm quyết định im lặng của model. Chỉ
  data thật + LLM thật mới lòi ra.
- **Review tìm ra lỗi vĩnh viễn mà UAT thật cũng không gặp.** `read_pending_actions`
  raise khi `approvals.db` chỉ có bảng `approval_rules` — một agent như vậy giết tín
  hiệu approval của TOÀN fleet, mọi nhịp, và tự CI lẫn fleet thật đều xanh vì chưa agent
  nào rơi vào trạng thái đó. Docstring lúc viết đã cân nhắc đúng đánh đổi "1 agent hỏng
  = mất cả tín hiệu" nhưng cho *blip tạm thời*; lập luận đó sụp khi trạng thái là VĨNH
  VIỄN. Bài học: khi nhận một đánh đổi "an toàn theo hướng này", phải hỏi trạng thái xấu
  đó tự khỏi được không.
- **Sửa ở NGUỒN vì reader dùng chung.** Cùng hàm đó đang đỡ cả digest lẫn lệnh chat
  `xem việc chờ duyệt`, nên cô lập lỗi trong vòng lặp collector chỉ vá một nửa.
- **Đọc plan không thay được đọc code.** Plan ghi `agent/secretary_heartbeat_digest.py`,
  file thật ở `runtime/`. Tìm bằng grep `HeartbeatDigest` thay vì tin đường dẫn.

## Mở / sang sau

- Bài học reflection đang bị `storage_hygiene` quét chung mốc 90 ngày với fact chat
  thường. Có thể đúng ý, nhưng nên là quyết định có chủ đích: "bài học từ việc đã giao"
  và "CEO thích họp buổi sáng" không hiển nhiên cùng vòng đời.
- Rule CRUD (xem/thu hồi) vẫn chỉ ở CLI/web — chat chỉ TẠO được rule. Cố ý (YAGNI), mở
  lại nếu CEO thấy vướng.
