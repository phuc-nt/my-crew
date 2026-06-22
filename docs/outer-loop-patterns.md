# Outer Loop Patterns — my-project-manager

> **Forward-looking research doc.** KHÔNG implement bây giờ. Đọc/triển khai SAU khi core MVP (Phase 1) chạy ổn.
> Mục đích: phác sẵn các outer loop hữu dụng cho agent management, để khi core xong thì research + build tiếp có hướng.

## 0. Khái niệm (ngắn)

- **Inner loop** = vòng tự có mỗi turn của agent: reason → act → observe → reason. KHÔNG thiết kế, có sẵn.
- **Outer loop** = tầng meta tự dựng: lặp nhiều inner loop, tự feed task + tự quyết khi nào dừng.
- 3 thành phần một loop đúng nghĩa: **Goal** (điều kiện dừng đo được) · **Loop** (lặp bounded N / tới khi điều kiện true) · **Routine** (chuỗi hành động gọi được mỗi vòng).
- 2 kiểu: **progress-driven** (push tới hoàn thành, có goal-checker) vs **time-driven** (canh thay đổi theo lịch, không "done").
- **Maker–checker**: model làm việc ≠ model kiểm "đạt goal chưa" → chống agent tự gian lận điều kiện dừng (reward hacking). Checker nên model rẻ (Haiku).
- ⚠️ Outer loop **không bù** được inner loop yếu — chỉ khuếch đại. Lặp 100 lần model kém = đốt tiền nhanh hơn.

> Core MVP hiện tại (perceive→analyze→report, xem `system-architecture.md §3`) là **Routine**, chưa phải outer loop. Các pattern dưới BỌC routine đó trong vòng lặp có goal/lịch.

## 1. Loop A — Monitoring Loop (time-driven) ⭐ ưu tiên đầu

**Mục tiêu**: agent canh trạng thái dự án định kỳ, chỉ báo khi có gì đáng chú ý (không spam mỗi lần).

```
LOOP mỗi N (vd 2h, hoặc cron 9h/13h/17h):
  routine = perceive (Jira + GitHub) → analyze → detect risks
  IF có risk MỚI (chưa báo) → compose + deliver Slack
  ELSE → im lặng, ghi state "đã check, không có gì mới"
  → ngủ tới lần sau
```

- **Kiểu**: time-driven (không có "done"). Dừng = người tắt / kill switch.
- **Goal-check**: không phải "đạt goal" mà là "có thay đổi đáng báo không" → so với state lần trước (dedup risk đã báo).
- **Routine**: chính là core MVP.
- **Phanh**: dedup (idempotency — đừng báo lại cùng 1 risk), rate-limit Slack, budget cap.
- **Map sang Claude Code**: `/loop` với interval, hoặc cron (giống OpenClaw Morning Briefing). Bản chất giống cron sẵn có.
- **Vì sao ưu tiên**: ROI cao nhất, rủi ro thấp (chủ yếu read + 1 post có điều kiện), gần với MVP nhất.

## 2. Loop B — Goal-Driven Resolution Loop (progress-driven)

**Mục tiêu**: nhắm 1 đích đo được, lặp tới khi đạt hoặc hết budget. VD: "mọi blocker sprint có owner + next-action trên Jira".

```
GOAL = "0 blocker sprng thiếu owner/next-action" (đo được trên Jira)
LOOP tới khi GOAL đạt HOẶC chạm budget/max-iterations:
  maker:   routine → tìm blocker thiếu xử lý → đề xuất/ghi (qua Action Gateway)
  checker: model RIÊNG (Haiku) đọc lại Jira → "goal đạt chưa?" (true/false + lý do)
  IF checker=true → dừng, báo kết quả
  ELSE → vòng tiếp
```

- **Kiểu**: progress-driven. Có điều kiện dừng đo được.
- **Maker–checker BẮT BUỘC**: maker (agent chính) ≠ checker (Haiku đọc state thật). Không để agent tự nói "xong".
- **Goal phải quan sát được trong data thật** (Jira field), không mơ hồ. Spec gọn (~4000 ký tự nếu dùng `/goal`).
- **Phanh**: max-iterations (vd 5), budget, và **Lớp B interrupt** — action ghi Jira nhạy cảm vẫn hỏi người (xem PDR §7.9).
- **Map sang Claude Code**: `/goal` (checker Haiku có sẵn cơ chế). Hoặc tự code loop trong LangGraph (graph có node `check_goal` rẽ nhánh loop-back).
- **Rủi ro**: cao hơn Loop A vì write nhiều + autonomous → guardrail phải vững (Phase 2) trước khi bật.

## 3. Loop C — Scheduled Reporting Loop (time-driven, fixed cadence)

**Mục tiêu**: report định kỳ chắc chắn (daily standup digest, weekly sprint review) — luôn chạy đúng giờ, không phụ thuộc "có gì mới".

```
CRON (vd 9:00 hằng ngày / thứ 6 17:00):
  routine → perceive → analyze → compose report theo template → deliver Slack + Confluence
  (luôn gửi, kể cả "tuần này ổn, không rủi ro")
```

- **Kiểu**: time-driven, cadence cố định. Khác Loop A: A chỉ báo khi có gì mới; C luôn gửi đúng nhịp (nghi thức).
- **Goal-check**: không — chạy là gửi.
- **Phanh**: idempotency (1 report/kỳ, re-run không trùng), budget.
- **Map sang Claude Code**: cron / scheduler. Đây là thứ MVP Phase 1 đã nhắm (daily digest + weekly report).

## 4. Chọn loop nào khi nào

| Tình huống | Loop |
|---|---|
| Canh rủi ro liên tục, báo khi cần | **A — Monitoring** (làm trước) |
| Đẩy 1 việc tới hoàn thành (đo được) | **B — Goal-driven** (cần guardrail vững) |
| Report nghi thức đúng nhịp | **C — Scheduled** (đã trong MVP) |

Có thể **lồng nhau**: Loop C (weekly report) gọi Loop B bên trong ("trước khi viết report, đảm bảo mọi blocker có owner đã").

## 5. Khung tổng quát để thiết kế outer loop mới (tái dùng)

```
1. Có đích đo được không?
   ── có  → progress-driven: cần GOAL (quan sát trong data thật) + checker (Haiku, ≠ maker)
   ── không → time-driven: cần INTERVAL/cron + điều kiện "đáng báo" (dedup vs state cũ)
2. Mỗi vòng làm gì? → 1 ROUTINE rõ ràng (core MVP / sub-flow)
3. Phanh: budget cap ($50/th) + max-iterations + kill switch + idempotency
4. Chống gian lận: maker ≠ checker (mọi loop progress-driven)
5. An toàn: action nhạy cảm vẫn qua Lớp A hard-block / Lớp B interrupt (PDR §7.9)
```

## 6. Quan hệ với guardrail hiện có

Outer loop **khuếch đại** số lần agent hành động → guardrail càng quan trọng:
- Budget $50/tháng (PDR §7.8) — loop chạy nhiều dễ chạm trần → hard-stop phải hoạt động.
- Kill switch — dừng loop đang chạy sai tức thì.
- Idempotency — loop lặp KHÔNG được tạo trùng ticket/report.
- Maker–checker — điều kiện dừng không do chính agent tự chấm.

## 7. Việc khi research tiếp (sau Phase 1)

- [ ] Chọn implement Loop A trước (gần MVP, ROI cao).
- [ ] Quyết: dùng `/goal` `/loop` của Claude Code, hay tự code loop trong LangGraph graph (node check + edge loop-back)? — so 2 cách.
- [ ] Định nghĩa checker: model gì (Haiku qua OpenRouter?), đọc state nào để chấm goal.
- [ ] Thử nghiệm 1 goal-driven loop nhỏ với budget thấp trước khi mở rộng.

## Unresolved

1. Checker chạy bằng model riêng (Haiku) qua OpenRouter — có nằm trong budget $50 chung không, hay tách?
2. Loop A interval bao nhiêu là hợp (2h? theo giờ làm việc?) — chờ dữ liệu thực tế dự án.
3. Tự code loop trong LangGraph vs dùng `/goal` `/loop` Claude Code — đợi đánh giá khi core xong.

Related: `system-architecture.md §3,§5` · `project-overview-pdr.md §7` · `project-roadmap.md`.
