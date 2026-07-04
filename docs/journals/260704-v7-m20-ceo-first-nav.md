# v7 M20 — CEO-first navigation: nav 4 mục + Việc gộp + badge

2026-07-04 · ✅ Done · (kết thúc v7)

Gom nav 12 mục ngang hàng thành 4 mục CEO cần mỗi ngày. "Mở app là biết bấm gì". FRONTEND-ONLY — backend 0 đổi (diff chỉ web/ + static build).

## Làm gì
- **Nav 4 mục** (`Layout.tsx`): **Trợ lý** (chat, mặc định `/`) · **Đội** (team) · **Việc** (work, có badge) · **Cài đặt** (settings). Bỏ agent-picker toàn cục khỏi header.
- **Trang Việc** (`Work.tsx` mới): gộp 1 trang — khối "Cần bạn duyệt" (approvals MỌI agent, aggregate client-side, 2-step confirm approve/reject) + khối "Việc đã giao" (nhúng `<Tasks/>` M15b sẵn có).
- **Badge chờ duyệt**: `use-pending-approvals.ts` fan-out `getAgents()→getApprovals(id)` mọi agent, đếm pending, poll 30s. KHÔNG route mới (red-team SCOPE-2: `/api/agents/{id}/approvals` đã có). Badge đỏ trên "Việc".
- **Cài đặt** (`Settings.tsx` mới): kết nối (integration health) + **Nâng cao** link 7 view kỹ thuật (Tổng quan/Timeline/Chi phí/Bộ nhớ/Guardrail/Cấu hình/Chạy thủ công) + Tài liệu + Tạo.
- **AdvancedAgentView** (wrapper): 7 view per-agent cần `useAgent()` → bọc kèm AgentPicker (picker bỏ khỏi nav chung nhưng vẫn có ở đúng chỗ cần).
- **App.tsx**: index→`/chat`; URL cũ `/approvals`+`/tasks`→`/work` (Navigate replace, bookmark không chết).
- **Chat quick chips**: 3 câu cố định ("Đội mình đang thế nào?"...) + chip động "⚠️ N việc chờ duyệt" (Link→/work) khi pending>0.
- **UAT checklist**: cập nhật bản đồ menu 4 mục + đường đi mới (Approvals→Việc, Team→Đội).

## Nguyên tắc: KHÔNG mất chức năng
Cả 13 đích cũ vẫn tới được: Approvals/Tasks gộp vào Việc; 7 view kỹ thuật vào Cài đặt→Nâng cao; URL cũ redirect. Reviewer trace từng đích: đều routed + linked/redirect. Backend 0 route đổi — aggregate là client fan-out trên endpoint agent-scoped sẵn có (allowlist/gateway bất biến).

## Review: no-function-lost OK, H1 vá
- **H1 (HIGH) double-poll `/chat`**: Layout badge + Chat chip mỗi cái mount `usePendingApprovals` riêng → trang mặc định fan-out `2×(1+N)` request/30s + 2 badge lệch nhau. Vá: `PendingApprovalsProvider` (context) bọc Layout → 1 poll chung, Layout+Chat đọc `useSharedPendingApprovals` (ngoài provider → EMPTY, không fan-out, không conditional-hook).
- **M1 (vá)**: `AgentPage` link `/approvals`→`/work` (bỏ redirect bounce).
- Xác nhận tốt (reviewer): approve gọi đúng `api.approve(agentId, id)` với agentId từ item aggregate; per-agent getApprovals fail → drop `[]` không blank cả bảng; clearInterval cleanup; sendText không stale-closure; redirect replace; ConfirmDialog render `item.action` từ API không dựng client-side.
- Giữ `Approvals.tsx` orphan (harmless, redirect lo; fallback component).

## Verified
56 vitest (+6: Work aggregate/approve-scoped/reject/empty, Layout 4-mục+badge) + tsc + oxlint (chỉ 2 warning fast-refresh pre-existing) + vite build. Py 1140 KHÔNG đổi (backend bất biến). Route tests chứng minh 4 mục + badge + redirect + approve agent-scoped.

## Bài học
- **Backend 0 đổi = client aggregate trên endpoint sẵn có**: badge không cần `/api/work/summary` — fan-out `getApprovals` mọi agent + đếm. Red-team SCOPE-2 đúng: thêm route chỉ khi ĐO ĐƯỢC N-request là vấn đề (LAN nhỏ → không).
- **Gom nav = đổi chỗ đứng, KHÔNG xóa**: mọi view giữ nguyên component, chỉ chuyển vào Nâng cao/trang agent + redirect URL cũ. "Không mất chức năng" là bất biến, verify bằng trace từng đích.
- **Hook mount nhiều nơi = poll nhân bản**: badge + chip cùng dùng hook fan-out → context provider 1 nguồn. Fallback EMPTY (không hook điều kiện) giữ component tự-đủ trong test.
- **Bỏ global picker phải thay bằng picker cục bộ**: 7 view per-agent vẫn cần agent chọn → wrapper AdvancedAgentView kèm picker, không để view kẹt empty-state.

## v7 hoàn tất
M17 (installer+wizard) → M18a (agent chạy-ngay telegram) → M18b (knowledge form+skills) → M19 (Company Docs) → M20 (nav CEO-first). Sản phẩm: cài 1 lệnh + wizard → tạo agent chạy ngay → nuôi knowledge + tài liệu công ty → dùng qua 4 mục. Backend logic/graph/gateway/THE INVARIANT nguyên vẹn; v7 chỉ thêm route mỏng + đổi mặt tiền.
