# my-project-manager

Agent (LangGraph) thay thế / giảm ~90% cost các vai **management** (PM, SM, Team Lead) trong team AI-native — tự động hóa qua **Slack · Jira · Confluence · GitHub**.

Team Dev đã có bộ tool AI hoàn chỉnh; nhóm management thì chưa. Repo này lấp khoảng đó: agent **chủ động** đọc trạng thái dự án → suy luận → hành động (report, monitor tiến độ, cảnh báo rủi ro) như một PM thật.

## Trạng thái

**Phase 0 — khởi tạo** (2026-06-21). Chưa có code; mới có docs + scaffold rules. Xem `docs/project-roadmap.md`.

## Quyết định đã chốt

- **Framework**: LangGraph (Python).
- **Runtime giai đoạn đầu**: CLI / local; scale lên service + Slack UI sau.
- **MVP**: Reporting + progress monitoring (đọc Jira/GitHub → report → Slack/Confluence).
- **Write authority**: Full autonomous — ⚠️ kèm guardrail bắt buộc (audit / dry-run / kill-switch / scoped token / idempotency). Xem `docs/project-overview-pdr.md §7`.

## Đọc gì trước (cho agent kế tiếp)

1. `docs/project-overview-pdr.md` — vấn đề, mục tiêu, scope, **guardrail §7**, unresolved §9. **ĐỌC ĐẦU TIÊN.**
2. `docs/system-architecture.md` — kiến trúc tầng, graph LangGraph, Action Gateway.
3. `docs/project-roadmap.md` — phase + việc cần làm theo thứ tự.
4. `docs/code-standards.md` — quy ước code + quy tắc riêng (mọi write qua Action Gateway).
5. `docs/codebase-summary.md` — bản đồ "cái gì ở đâu" + **Reference & Docs** (path deer-flow + link docs lib).
6. `docs/design-guidelines.md` — nguyên tắc hành vi agent (cư xử như PM đáng tin).
7. `docs/deployment-guide.md` — setup, secrets scoped, kill switch, cron.

Tham khảo khi cần (không bắt buộc đọc đầu): `docs/reference-deerflow-2-architecture.md` — phân tích kiến trúc DeerFlow 2.0 (harness production trên LangGraph, học pattern, KHÔNG copy).

Cùng với `CLAUDE.md` (workflow + rules) ở root.

## Bối cảnh

Dự án độc lập, không phụ thuộc OpenClaw/Hermes. Reference learning có sẵn: `~/workspace/deer-flow` (DeerFlow 2.0 — harness production xây trên LangGraph). Path subsystem cụ thể + link docs lib (LangGraph/OpenRouter/SDK) ở `docs/codebase-summary.md → Reference & Docs`.
