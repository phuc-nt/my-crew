# Dev Journal — my-project-manager

Dòng thời gian phát triển kiến trúc + tính năng (repo vừa-làm-vừa-học). Đọc bảng dưới để thấy cả hành trình; mở từng file cho chi tiết.

**Quy ước:** 1 file / mốc, **tiền tố ngày** `YYMMDD-<slug>.md` (vd `260622-phase-1-slice-2-confluence-report.md`) → sắp xếp theo thời gian, mỗi mốc tự ghi ngày. Súc tích theo template — chỉ ghi cái verify được, không bịa, không kể lể. Ghi ở mốc (phase/slice xong hoặc sự kiện đáng nhớ).

## Dòng thời gian

| Ngày | Mốc | Trạng thái | Tóm tắt |
|---|---|---|---|
| 2026-06-21 | [Phase 0 — Scaffold](260621-phase-0-scaffold.md) | ✅ Done | Hello-agent (LangGraph) + guardrail core. Chốt: tool qua MCP+CLI; allowlist + Lớp A hard-deny (2 vòng review). E2E OpenRouter OK. |
| 2026-06-21 | [Phase 1 Slice 1 — Reporting](260621-phase-1-slice-1-reporting.md) | ✅ Done | Jira+GitHub→Slack qua gateway. Agent SPAWN MCP subprocess (stdio-only). E2E post Slack thật. |
| 2026-06-22 | [Phase 1 Slice 2 — Confluence](260622-phase-1-slice-2-confluence-report.md) | ✅ Done | Report detail→Confluence + short+link→Slack. E2E thật cả 2. State chỉ primitive (fix checkpoint). |

## Template entry (`YYMMDD-<slug>.md`)

```markdown
# <Tiêu đề mốc>
<ngày> · <trạng thái>

## Làm gì
3-5 gạch: tính năng/kiến trúc đã build (cái verify được).

## Quyết định & vì sao
Bảng: Quyết định | Vì sao | Đánh đổi. Chỉ mốc đáng nhớ.

## Vấp & học được
2-4 gạch: sai gì → rút ra gì. Ngắn.

## Mở / sang sau
1-3 gạch.
```

Sau khi viết entry, thêm 1 dòng vào bảng dòng thời gian trên.
