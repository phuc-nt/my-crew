---
phase: 1
title: Personal pack + hồ sơ thư ký + chat lõi
status: completed
priority: P1
effort: 1d
dependencies: []
---

# Phase 1: Personal pack + hồ sơ thư ký + chat lõi

## Overview

Domain pack mới `personal-pack` (product code) + profile thư ký (user-data) + bot Telegram riêng.
Kết thúc phase: nhắn DM bot → thư ký trả lời đúng persona, autonomous, dry_run off.

## Requirements

- Functional: DM bot thư ký → trả lời qua pipeline `answer_mention` (qa_answer.py); persona tiếng
  Việt ngắn gọn kiểu Pong; chat allowlist chỉ CEO.
- Non-functional: pack mới không phá pack hiện có; profile là user-data KHÔNG commit; token bot
  chỉ ở env (`bot_token_env`), không bao giờ vào yaml/audit.

## Architecture

- **Pack** `domain-packs/personal-pack/`: scaffold từ `_template-pack` (pack.yaml, prompts/,
  tools.py, write_handlers.py, graphs.py). Persona + phạm vi thư ký nằm trong prompts của pack;
  hồ sơ cá nhân (thói quen CEO) nằm trong `profiles/<id>/SOUL.md` + `MEMORY.md` (đọc verbatim
  bởi loader — đã hỗ trợ sẵn).
- **Profile** `profiles/thu-ky/profile.yaml` (user-data): `domain: personal`,
  `agent_runtime: create_agent` (tier tool-calling read-only — jira/github/history reads),
  `telegram: {bot_token_env: THU_KY_BOT_TOKEN, chat_ids: [<CEO chat id>], ops_operator_id: <CEO>}`,
  `safety: {dry_run: false, trust_mode: autonomous}`, `budget`, `model` + `model_chain` fallback.
- Inbox tự vào lịch qua pseudo-kind `inbox` (inbox_dispatch.py) — không cần code mới.

## Related Code Files

- Đọc trước: `domain-packs/_template-pack/*`, `my_crew/packs/registry.py` (cách pack được
  discover/đăng ký), `my_crew/runtime/telegram_inbox.py`, `my_crew/agent/qa_answer.py`,
  `my_crew/config/telegram_config.py`, `demo/profiles/truong-phong/profile.yaml` (mẫu).
- Create: `domain-packs/personal-pack/` (pack.yaml, prompts, tools.py, write_handlers.py, graphs.py),
  tests cho pack (theo mẫu test pack hiện có), `profiles/thu-ky/` (user-data, không commit).
- Modify: chỗ đăng ký domain hợp lệ nếu registry không auto-discover (xác minh khi đọc registry.py).

## Implementation Steps

1. Đọc registry + _template-pack → xác định contract tối thiểu của 1 pack (graph nào bắt buộc,
   prompt nào qa_answer cần). Ghi lại trước khi viết.
2. Scaffold `personal-pack`: persona thư ký (prompts), tools.py/write_handlers.py tối thiểu
   (chưa cần write handler riêng — telegram_send là handler chung), report kinds để trống hoặc
   tối thiểu (briefing sang Phase 2).
3. Tests pack: load pack, build graph QA, prompt chứa persona; theo pattern test của admin-pack.
4. **User action:** CEO tạo bot BotFather mới, đặt token vào env store hiện dùng
   (`~/.my-crew/.env`), báo chat id. KHÔNG in token ra terminal/log.
5. Tạo `profiles/thu-ky/` + SOUL.md (port ý từ IDENTITY/SOUL của Pong: tên, tiếng Việt, ngắn gọn,
   phạm vi: lịch/email/tài chính cá nhân/nhắc việc; KHÔNG làm research sâu — đẩy sang staff khác).
6. Restart com.mpm.service, verify schedule có `thu-ky | inbox`; UAT thật: nhắn DM → trả lời.

## Success Criteria

- [x] Pack `personal` load được, suite BE xanh (pack tests mới pass).
- [x] `thu-ky | inbox` xuất hiện trong /api/schedule/upcoming.
- [x] DM bot → trả lời đúng persona (tức thì, xem 1.5); người lạ nhắn → bị lọc allowlist.
- [x] Không có token trong yaml/log/audit; profile không nằm trong git status.

## Kết quả (2026-08-03)

- **Phát hiện đổi thiết kế (bước 1):** tier `create_agent` chỉ chạy team-step, chat DM luôn
  đi đường M11 ground qua `pack.tools.read(kind)` và pack BẮT BUỘC có ≥1 kind → pack sở hữu
  luôn kind `briefing` (graph perceive→compose→deliver Telegram) ngay phase 1. Phase 2 nhờ đó
  khỏi sửa core scheduler.
- **Review bắt H1:** `pack.allowlist or None` với allowlist rỗng có chủ đích âm thầm hồi sinh
  allowlist mặc định rộng của core — sửa ở graph pack + cùng-bẫy tại `qa_answer.py` (chat path),
  kèm test regression + test dedup non-dry-run. M1 (ops_operator_id phải thuộc chat_ids khi làm
  đích gửi) cũng sửa.
- **Phát sinh 1.5 (CEO yêu cầu giữa UAT):** chat phải tức thì như openclaw → thêm
  `my_crew/runtime/telegram_listener.py` — thread long-poll peek 45s per telegram agent,
  có tin spawn đúng worker inbox subprocess (isolation + pipeline nguyên vẹn), tick lịch giữ làm
  fallback, rate-cap 6 run/60s chống flood. +7 test. Suite 2406 BE xanh.
- **UAT thật 7/7 đạt** (đọc từ audit): ngày giờ đúng, nháp tốt, không bịa lịch, từ chối gửi mail
  đúng giới hạn, chặn prompt-injection dứt khoát, đẩy research cho crew. Race listener×tick bị
  dedup gateway chặn đúng (1 compose thừa ~$0.0004). Sửa prompt sau UAT: cấm markdown thô
  Telegram, khoá xưng hô em/anh, cấm trộn ngôn ngữ.

## Risk Assessment

- Pack contract ngầm (graph/prompt bắt buộc) → bước 1 đọc trước khi viết, không đoán.
- `dry_run: false` từ đầu: rủi ro thấp vì phase này agent chỉ trả lời Telegram vào chat allowlist;
  Lớp A + secret-scan vẫn nguyên.
- Bot token là user action — nếu chờ CEO, làm trước bước 1–3 (không chặn).
