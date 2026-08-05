# v67–v68 — Vòng "tự chủ có kỷ luật" (lifecycle · Lớp B học dần · nhịp thư ký · reflection)
2026-08-05 · hoàn thành

## Làm gì

- **Tách delivery khỏi execution** (P1): task chạy xong ≠ CEO đã thấy. Mọi task kết
  thúc đều có terminal outcome + delivery status truy vấn được — "never silently fail"
  thành hợp đồng chứ không phải thiện chí.
- **Lớp B học dần** (P2): `approval_rule_store.py` per-agent trong `approvals.db`;
  rule key derive từ `_MUTATING_TYPES` (không bịa taxonomy), `params_hash` bind bắt
  buộc cho kind hướng ngoài. Deny rule CHỈ áp `trust_mode="guarded"` (CEO chốt sau
  red-team), rule CRUD chỉ qua CLI/web (operator-bound) — bề mặt chat hoãn sang 2b.
- **Nhịp thư ký chủ động** (P3): pseudo-kind `secretary-heartbeat` + cron riêng, config
  `heartbeat.every` đặt ở **profile.yaml** chứ không company.yaml (`save_company` dựng
  lại từ dict cứng, key viết tay sẽ bị xoá). Digest chỉ gồm tín hiệu THẬT: task stalled,
  việc sweep đã bỏ cuộc, nhắc hẹn trong 24h, draft của chính nó. Im lặng thì miễn phí.
- **Reflection** (P4): task vào terminal → 1 lượt LLM nhỏ chưng cất bài học về **cách
  giao việc**, ghi vào `(coordinator_id, "memory")`. 5 điểm móc: done (SAU delivery leg,
  vì "xong" và "xong nhưng CEO không thấy" là 2 bài học khác nhau), dead-step,
  cap_exceeded, plan_hash, review-exhausted.
- Suite kết arc: **2692 BE passed, 9 skipped**, ruff sạch.

## Quyết định & vì sao

| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Lesson vào namespace của **coordinator**, không phải worker | Coordinator là agent GIAO việc → bài học là về cách nó giao. Ghi vào namespace worker sẽ phá ranh giới WO-self (`_assert_self_namespace`) | Bài học "agent-b cần tiêu chí gì" nằm ở coordinator, không ở agent-b — đọc gián tiếp qua sibling |
| Dùng lại namespace `memory` sẵn có | Sibling đọc được ngay qua `sibling_memory`, CEO thấy trong memory view — 0 lớp chia sẻ mới | Lesson trộn chung với fact thường, không lọc riêng được |
| Marker cooldown ra namespace RIÊNG `"reflected"` | Marker ghi mỗi lần, lesson thì hiếm → trộn chung sẽ chôn fact thật với 3 chỗ đọc `(agent_id,"memory")`. Và sweep retention 90d sẽ XOÁ marker, mở lại đường trả tiền lần hai cho task stalled lâu | Thêm 1 namespace phải nhớ khi đọc/dọn |
| Reflection inline + `_reflect_safely` nuốt mọi exception | `run_one_tick` không có except riêng → reflection lỗi sẽ giết tick. Bài học là "có thì tốt", trạng thái task mới là sự thật | Lỗi reflection chỉ vào log warning, dễ trôi |
| Cost chỉ tính trần tháng | `BudgetTracker` trong `LlmClient.complete()` đã chặn; thêm cột DB là YAGNI | Không truy được chi phí riêng của reflection |

## Vấp & học được

- **Guardrail chống "harden into refusal" chỉ chặn TOOL, quên chặn NGƯỜI.** "Đừng bao
  giờ giao việc phân tích cho agent-b nữa" lọt qua sạch. Đúng dạng thất bại Hermes
  nhưng nhắm vào đồng đội — tệ hơn, vì thành lệnh cấm tuyển dụng vĩnh viễn học từ đúng
  1 lần stall. Vá: `_BLANKET_REFUSAL_PATTERNS` kiểm tra ĐỘC LẬP với tên tool + cấm
  kết luận về năng lực người ngay trong prompt.
- **Guardrail phụ thuộc dấu tiếng Việt.** Model được bảo "trả 1 dòng ngắn" nên viết cả
  có dấu lẫn không dấu; "Mang chap chon nen buoc 2 that bai" đi thẳng vào memory bền.
  Vá bằng `_fold()` (NFD + bỏ dấu tổ hợp + `đ→d`).
- **Rồi chính cú fold đó đẻ bug ngược.** Bỏ dấu làm `đừng` ("don't") và `dùng` ("use")
  trùng token `dung` → pattern `\bdung\b` chặn nhầm "nên dùng web_search", tức là chặn
  đúng loại lesson routing mà tính năng sinh ra để giữ. Thu hẹp thành cặp động từ.
  Bài học: normalize để nới guardrail thì phải soát lại chiều ngược — token gộp lại
  làm pattern rộng ra một cách vô hình.
- **UAT mức module không chứng minh được dây có điện.** Vòng đầu gọi thẳng
  `make_reflect(...)` — tức test MODULE, đúng lỗi v66 "đã wired ≠ có điện". Làm lại ở
  mức tick thật, cả 5 điểm móc: dead-step, plan_hash, cap_exceeded, done (sau delivery
  leg), review-exhausted. Chỉ dead-step và review-exhausted đẻ lesson bền; 3 điểm kia
  model trả `KHONG_CO_GI` — đúng, hỏng hạ tầng không dạy gì về cách giao việc.
- **Cách ly UAT bằng monkeypatch trong-process là vô hình với process con.** Gán
  `team_task_paths.DATA_DIR` chỉ ăn ở tiến trình cha; worker spawn qua `Popen` đọc
  `MY_CREW_HOME` từ env nên vẫn trỏ `.data` thật. Cộng với `stderr=DEVNULL`, triệu
  chứng là step kẹt `running` không lý do. Cách ly đúng là env var — thứ process con
  thừa hưởng được.
- **Review đưa 1 finding sai cơ chế nhưng đúng kết luận.** Reviewer bảo marker sẽ đẩy
  lesson ra khỏi `search` (`ORDER BY updated_at DESC LIMIT`); thử thật 60 marker ở
  limit 10/20/40 — lesson vẫn còn, tiền đề sai với store này. Nhưng soi tay thì
  `visualize_views._fact` render marker thành fact rỗng và `storage_hygiene` quét
  marker ở mốc 90 ngày — vẫn vá, nhưng trên lý do đúng. Đo trước khi tin.

## Mở / sang sau

- Stall lần hai sau `retry_stalled_step` → `reopen_stalled` hiện KHÔNG reflect được
  (marker là "một lần mãi mãi"), trong khi đó mới là stall giàu thông tin nhất.
- Bề mặt chat cho approval (phase 2b): cần đường chat→ApprovalStore + binding
  `(agent_id, approval_id)` chống nhầm row (bài học v64 H1).
- `_task_digest` cố tình loại `result_text` (injection). Chỗ dựa còn lại là `step.title`
  do hệ thống sinh — nếu sau này fan-out cho phép step tự ĐỀ XUẤT title con từ output
  của nó, text chịu ảnh hưởng attacker sẽ vào prompt mà module này không đổi dòng nào.
