# Dev Journal — my-project-manager

Dòng thời gian phát triển kiến trúc + tính năng (repo vừa-làm-vừa-học). Đọc bảng dưới để thấy cả hành trình; mở `phase-N.md` cho chi tiết.

**Quy ước:** 1 file / phase (`phase-N.md`), ghi/cập nhật **cuối mỗi phase**. Súc tích theo template — chỉ ghi cái verify được, không bịa, không kể lể.

## Dòng thời gian

| Phase | Ngày | Trạng thái | Mốc chính |
|---|---|---|---|
| [0](phase-0.md) | 2026-06-21 | ✅ Done | Scaffold + hello-agent (LangGraph) + guardrail core. Chốt: tool qua MCP+CLI; guardrail allowlist + Lớp A hard-deny (sau 2 vòng review). E2E OpenRouter thật OK. |

## Template entry (`phase-N.md`)

```markdown
# Phase N — <tên>
<ngày> · <trạng thái>

## Làm gì
3-5 gạch: tính năng/kiến trúc đã build (cái verify được).

## Quyết định & vì sao
Bảng: Quyết định | Vì sao | Đánh đổi. Chỉ mốc đáng nhớ.

## Vấp & học được
2-4 gạch: sai gì → rút ra gì. Ngắn.

## Mở / sang phase sau
1-3 gạch.
```

Sau khi viết entry, thêm 1 dòng vào bảng dòng thời gian trên.
