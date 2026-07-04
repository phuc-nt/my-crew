# v8 M22 — Multi-project "agent tổng": portfolio roll-up

2026-07-04 · ✅ Done

Ràng buộc lớn nhất cho công ty >1 team/repo: single-project cứng, không cái nhìn tổng. M22 giữ 1 agent = 1 project, thêm report kind `project-rollup` gom summary báo cáo gần nhất từng agent thành 1 báo cáo tổng cho CEO. KHÔNG live-fetch, KHÔNG pack mới, KHÔNG multi-binding.

## Làm gì
- **`report_summary.py`**: `summarize_report(text, 500)` — regex strip tag (KHÔNG HTML parser), collapse whitespace, cắt ranh giới câu gần limit else hard-cut "…". Rỗng → "".
- **Worker ghi summary**: `_event(+report_summary)`; success path tính summary CHỈ khi `audience=="internal"` + có `report_text`. Field VẮNG khi rỗng → event byte-identical cho pseudo-kind (inbox/tasks/ops-alerts) + external run (backward-compat).
- **`project-rollup` kind admin-pack**: `build_project_rollup` nhóm agent theo project (jira_project_key/github_repo), lấy `last_run.report_summary`, **exclude fleet-read agent theo CAPABILITY** (`reports ∩ {project-rollup,cost-rollup,guardrail-health,audit-digest}` — không hardcode domain, red-team m3), never-run → "chưa có báo cáo". Reuse narrative prompt admin (kind-agnostic).
- **agent_state_reader** thêm `domain`+`project` vào state; `last_run` giữ raw event (nguồn INTERNAL cho rollup).
- **External block**: `build_fleet_graph` raise ValueError nếu kind=project-rollup + audience=external (chứa summary internal, không có form external).

## RED-TEAM B3 — leak qua status API → vá
`report_summary` là nội dung báo cáo trong runs.jsonl. `agent_views` (và MỌI view trả `last_run`) echo NGUYÊN event → thêm summary = leak content ra fleet-status API. Vá: `_public_last_run` **whitelist field** (ts/agent_id/kind/audience/status/cost_usd/delivered — loại report_summary); `list_agents`+`agent_status` dùng nó. Review trace TẤT CẢ client path: status API + **timeline** (`visualize_views.runs_view` — allowlist RIÊNG `_RUN_FIELDS`, cũng loại summary) + ops-chat status + admin alerts — tất cả không leak. Test khóa CẢ HAI allowlist (status + timeline).

## Review: B3 HELD mọi client path, 2 LOW
- Review trace exhaustive 6 client path đọc run event/fleet state → không path nào leak summary. Không CRITICAL/HIGH.
- LOW-1 (vá): B3 regression test chỉ khóa `_public_last_run`, không khóa timeline (allowlist thứ 2 độc lập) → thêm `test_report_summary_stripped_from_timeline` để 1 edit tương lai thêm summary vào `_RUN_FIELDS` sẽ đỏ test.
- LOW-2 (giữ): `<` không đóng để markup thô trong summary — bounded, không raise, internal-only (không leak) → cosmetic, YAGNI.

## Verified
1170 pytest (+17: report_summary bounded/tag-strip/sentence-cut/pathological-tag, project-rollup group/exclude-capability/never-run/no-project, external-block, B3 status+timeline strip, worker internal-writes/external-omits/no-text-omits) + ruff. **E2E LIVE data thật** (hr+sales-pm 2 project khác nhau, non-destructive restore): 2 summary gom đúng vào rollup, admin excluded, project key đúng (SCRUM), **status API last_run KHÔNG có report_summary** (B3), external audience blocked.

## Bài học
- **Thêm field vào log dùng-chung phải rà MỌI client path**: `report_summary` vào runs.jsonl không tự an toàn — `agent_views` + `visualize_views` (timeline) đều echo event ra client. Mỗi surface là allowlist RIÊNG → phải vá + test từng cái. Reviewer trace exhaustive là load-bearing (tôi vá status API, reviewer nhắc timeline là allowlist thứ 2).
- **Exclude theo NĂNG LỰC không theo tên**: chống đệ quy rollup bằng `reports ∩ fleet-kinds` (capability) chứ không `domain=="admin"` → pack fleet-read thứ 2 tự động được che.
- **Field additive omit-khi-rỗng = backward-compat**: event cũ/pseudo-kind/external không có field → reader tolerant, byte-identical. Không cần version schema.
- **Strip tag = regex text-extraction bounded TRƯỚC cut, không HTML parser**: tag bệnh hoạn không phá bound + không execute gì (red-team m4).

## Unresolved / next
1. M23: trust ladder dual-surface (`scheduled_reports:` approval_gate + `actions:` gateway-enqueue) + code-review adversarial riêng.
