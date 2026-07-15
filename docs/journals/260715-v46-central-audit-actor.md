# v46 — central-audit actor (attribute every gateway action + approval to its agent)
2026-07-15 · ✅ Done (2324 BE)

Benchmark v45 chấm governance của my-crew thắng dứt khoát NHƯNG lộ 1 gap thật: audit phân-biệt agent CHỈ qua PATH (data_dir per-agent), KHÔNG có field → dashboard đa-agent không filter được "ai làm gì" (fleet view phải reconstruct agent_id từ vòng lặp thư mục). Đóng gap: thêm field `actor` (agent profile_id) từ đầu tới cuối. Governance-only — 0 đổi hành vi guard.

## Làm gì
- **Field `actor`**: `AuditEntry.actor` (JSONL → **0 migration**, row cũ đọc absent) + `approvals.actor` (sqlite, **ALTER migrate-free** try/except OperationalError). `PendingApproval.actor` + query filter.
- **1 choke point**: `ActionGateway.__init__(actor="")` → `_record`→`AuditEntry(actor=self._actor)` stamp MỌI outcome branch (allow/deny/dry/dedup/kill/no-handler/error/pending/reject/rate-limit) qua 1 chỗ. Cả 2 site `enqueue` truyền actor.
- **16 agent-site** thread `getattr(loaded,"profile_id","")` (report graph dùng `context.agent_id`, operator_notify dùng `admin.profile_id`). **2 operator-CLI** (cli/automate) để `actor=""` có comment (lệnh người, không phải agent).
- **Read**: `AuditLog.query(actor=...)` filter chính xác (loại row no-actor); `_AUDIT_FIELDS += "actor"` → fleet/agent view project field GHI THẬT thay vì reconstruct từ path.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Đóng gap actor (không đua tốc-độ/cleverness) | benchmark: moat my-crew LÀ governance; đây là gap compliance thật, effort thấp | — |
| 1 choke point `_record` | mọi outcome branch attribute đồng nhất, không sửa từng branch → 0 risk đổi hành vi | — |
| Hash/field default "" | JSONL row cũ + caller cũ byte-identical; migrate-free | — |
| 2 CLI để actor="" | lệnh người (list/approve/reject), không phải agent action → attribute nhầm là sai | — |
| mpm_manage attribute target-agent (không "") | action được duyệt THUỘC agent đó, không phải operator → attribution hữu ích hơn | Khác 2 CLI kia (cosmetic) |

## Vấp & học được
- **AuditEntry required-field trap tránh được**: đặt `actor` dạng defaulted ("") ngay từ đầu → không phá site construction nào (bài học từ v45 TeamStep). JSONL nên còn dễ hơn dataclass sqlite.
- **Test action-type**: test viết `slack_post` không phải mutating type gateway nhận (chỉ mcp_tool/gh_cli/... ) → sửa dùng `mcp_tool`. Read action bypass gateway.
- **profile var khác nhau per-site**: loaded (runner) / context.agent_id (report graph, str|None nên `or ""`) / admin (operator_notify) — verify từng cái đúng field, không copy mù.

## Mở / sang sau
- Dashboard UI filter theo actor (v46 ghi field + query + projection; UI richer là việc riêng).
- Phân biệt human-requester vs agent-actor cho chat-approved (scout: `sender_id` có sẵn) — non-goal wave này.
- Tiếp theo (benchmark khuyến nghị): #2 Seatbelt exec-tier (red-team kỹ trước — Seatbelt deprecated), #5 giảm MCP overhead.
