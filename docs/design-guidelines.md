# Design Guidelines — my-crew

**Status:** Updated 2026-07-19 (v54 office cockpit layout; web UI design system + trust model).

> Đây là agent backend + web frontend (React SPA). "Design" bao gồm: (1) nguyên tắc thiết kế HÀNH VI agent (agent cư xử như PM/SM đáng tin), (2) thiết kế UI/UX web dashboard (dark mode, responsive, WCAG AA).

## 1. Triết lý hành vi agent

Agent đóng vai management → phải hành xử như một PM/SM **giỏi và đáng tin**, không phải bot máy móc:

1. **Chủ động, không thụ động** — không chờ hỏi mới làm; tự phát hiện rủi ro tiến độ và nêu ra.
2. **Dựa số liệu, không phán đoán mù** — mọi kết luận tiến độ phải truy về data Jira/GitHub thật. Không "đoán" trạng thái.
3. **Ngắn gọn, đúng audience** — report cho team khác cho stakeholder. Không dump raw data; chắt lọc cái cần hành động.
4. **Minh bạch lý do** — khi agent hành động (tạo ticket, cảnh báo), nêu *vì sao*. Truy vết được (gắn audit).
5. **Khiêm tốn ở vùng xám (v30 scoped)** — trong guarded mode hoặc khi dry_run, việc nhạy cảm/khó đảo ngược → dừng hỏi người (architecture §5.2). Autonomous mode chạy ngay (accept risk) kèm full audit rationale.

## 2. Nguyên tắc report (MVP trọng tâm)

- **Lead with the signal**: mở đầu bằng cái quan trọng nhất (rủi ro/blocker), không phải liệt kê tuần tự.
- **Actionable**: mỗi rủi ro nêu kèm "ai/cái gì cần làm", không chỉ mô tả vấn đề.
- **So sánh có mốc**: tiến độ so với sprint goal / kế hoạch, không chỉ con số trần.
- **Không nhiễu**: bỏ thông tin không đổi/không cần hành động.
- **Định dạng nhất quán**: theo template (chốt ở Phase 1) → người đọc quen mắt.

## 3. Nguyên tắc hành động (write)

- **Reversible-first**: ưu tiên hành động đảo ngược được (comment > xóa; draft > publish trực tiếp khi nhạy cảm).
- **Không spam**: idempotent — không post trùng, không tạo trùng ticket khi re-run.
- **Đúng kênh**: post đúng channel/space; sai chỗ là sự cố niềm tin.
- **Tôn trọng con người trong vòng lặp**: khi đụng việc của người thật (đổi assignee, đổi scope), thông báo/hỏi thay vì lặng lẽ làm.

## 4. Giọng & ngôn ngữ

- Report mặc định **tiếng Việt** (team Việt) trừ khi audience cần khác — chốt với chủ dự án.
- Giọng: chuyên nghiệp, thẳng, thực dụng. Không hoa mỹ, không hype.
- Số liệu rõ ràng; khi suy luận/không chắc → nói rõ là suy luận, không khẳng định như fact.

## 5. Web UI Design System (v9 M3 + M4, v10 M24 — design-token + dark mode + responsive)

### 5.1 Design Token (CSS-only, zero dependencies)

**Principle**: Centralized design decisions in `:root` CSS variables. No UI kit — giữ triết lý vanilla, zero NPM bloat.

**Token categories** (`web/src/App.css`):

| Category | Token names | Example values (light → dark) |
|----------|------------|------|
| **Semantic color** | `--color-text`, `--color-muted`, `--color-subtle`, `--color-border`, `--color-bg` | black → white-text; #6b6b6b → lighter gray; etc. |
| **Status colors** (role-split) | `--color-{danger,ok,warn}` (text) + `-solid` (nền đặc + white text) + `-bg` (nền nhạt) + `--color-on-{status}` | Separate roles: text ≠ white-on-filled ≠ background tint → WCAG AA both themes |
| **Spacing** | `--space-1`, `--space-2`, `--space-3`, `--space-4`, `--space-5` | 0.25rem, 0.5rem, 0.75rem, 1rem, 1.5rem |
| **Radius** | `--radius-sm`, `--radius`, `--radius-lg`, `--radius-pill` | 4px, 6px, 10px, 999px |
| **Shadow** | `--shadow-sm` | `0 1px 3px rgba(0, 0, 0, 0.08)` |
| **Type scale** | `--fs-h1` through `--fs-xs` | 1.4rem, 1.2rem, 1.05rem, 0.95rem, 1rem, 0.9rem, 0.8rem, 0.75rem |

**Implementation**: 112+ `var()` usages across components. **WCAG AA verified**: all roles (text-on-bg, white-on-filled, hint-on-bg) ≥4.5:1 both light + dark.

**Token organization by light/dark** (actual values from `web/src/App.css`):
- **Light (default `:root`)**: `--color-text` #1a1a1a, `--color-bg` #fafafa, `--color-surface` #fff; `--color-danger` (text) #b00020, `--color-danger-solid` (fill under white text) #b00020, `--color-warn` #9a5b00, `--color-ok` #1e7e34.
- **Dark (`[data-theme=dark]`)**: `--color-text` #e8e8e8, `--color-bg` #121212, `--color-surface` #1e1e1e; `--color-danger` (text) #ff8a80, `--color-danger-solid` (fill under white text) #c5221f, `--color-warn` #e0a03e, `--color-ok` #6bd68a. Text and solid-fill roles diverge in dark precisely because one hue can't serve both at AA once inverted.

### 5.2 Theme system (light/dark/auto, localStorage-persisted)

**Files**:
- `web/src/theme-context.tsx` — React context: resolveTheme (light|dark|auto), persist to `localStorage['theme']`, listen to system `prefers-color-scheme`.
- `web/src/components/ThemeToggle.tsx` — 3-state toggle (Sáng/Tối/Tự động); stored in context.
- `web/src/App.css` — Anti-FOUC inline script in `index.html` (mirror applyTheme logic) sets `data-theme` + `theme-color` meta **before React mounts** → zero flicker on page load.
- **`color-scheme: light/dark`** in root → native select/input/scrollbar follow theme.

**Behavior**:
1. User lands → inline script read `localStorage['theme']` → set `<html data-theme>` immediately (FOUC-free).
2. React mounts → `ThemeContext` normalizes + stores in state → UI components read via hook.
3. User toggles → context updates state + `localStorage`, then CSS re-evaluates `:root` or `[data-theme]` rules.
4. OS theme changes (auto mode) → prefers-color-scheme listener triggers re-resolve.

### 5.3 Primitives — The 6 UI Components (v53)

**Principle**: ONE canonical class per component type. All new styles MUST use tokens + primitives; no ad-hoc button/card/badge/input/empty-state classes.

**Files** (`web/src/components/ui/`):

| Component | React wrapper | CSS class(es) | Purpose |
|-----------|---|---|---|
| **Button** | `<Button variant="primary\|danger\|ghost\|chip">` | `.btn`, `.btn-primary`, `.btn-danger`, `.chip` | Actions. `type="button"` default (explicit `type="submit"` in forms). |
| **Card** | `<Card>` | `.card` | Surface (--space-3 padding, --radius, shadow-sm). Extra chrome via className. |
| **Badge** | `<Badge tone="ok\|warn\|danger\|accent\|neutral">` | `.badge`, `.badge-{tone}` | Status indicator; always pill-shaped (replaces drifted 10px variants). |
| **Input** | `<Input>` | `.ui-input` | Form field; one border/radius/padding app-wide. |
| **EmptyState** | `<EmptyState>` | `.ops-chat-empty` | Muted italic line (nothing-here moment). |
| **PageHeader** | `<PageHeader title={…} actions={…}>` | `.page-header`, `.page-header-actions` | Page title left, actions right, aligned baseline. |

**Header rule (v53)**: New view styles MUST extend these 6 primitives. Visuals stay in `App.css` section 3 (PRIMITIVES), behaviors in React. DISALLOWED: `.my-button`, `.card-accent`, `.input-lg` — reuse existing classes or propose token addition.

### 5.4 Font: Be Vietnam Pro (OFL, self-hosted)

**Why**: Serve Vietnamese + Latin glyphs via self-hosted woff2 (no CDN, offline-safe, CSP-friendly).

**Files**:
- `web/src/assets/fonts/` — 8 woff2 files (BeVietnamPro-Regular, -SemiBold, -Bold, etc.).
- `web/src/fonts.css` — `@font-face` + `unicode-range` subset (Vietnamese + Latin); total 96KB (well within budget).
- `App.css` applies `font-family: "Be Vietnam Pro", system-ui, sans-serif`.

**Load strategy**: Browser only fetches files if that weight/style is used on the page (unicode-range filtering).

### 5.5 Language Mode — VN/EN Toggle (v53)

**Architecture** (`web/src/i18n/`):

- **`LanguageProvider`** — React context (default 'vi'), persisted to `localStorage['ui-lang']`. Hook: `useLanguage()` → `{ lang, setLang, t }`.
- **Dictionary** (`dictionary.ts`) — ONE source of truth: `vi` keys are canonical; `en` maps must satisfy TypeScript compile check (missing/extra keys = error).
- **Translate function** `t(key, params?)` — FE-static strings only. Backend-origin strings (health-check labels, API error details, clarify questions) and LLM content stay Vietnamese in EN mode (they are data, not layout).
- **UI toggle** — VN/EN chip in header next to theme toggle, visible on all pages.

**Boundary (v1 decision, enforced)**: 

- **Translates in EN mode:** View labels, navigation, button text, UI chrome (all FE-static strings in `labels.ts` + `dictionary.ts`).
- **Stays Vietnamese in EN mode:** Health-check status/labels/hints, API error details, LLM-generated content (reports/clarifications), backend-origin strings — these are data flowing *from* backend, not layout.
- **Technical terms stay English in BOTH languages:** Captures, Guardrail, PIC, deep_agent, sandbox, engine, tokens, MCP, attempt, autonomous, guarded. CEO decision to keep these untranslated for clarity.

**Files**:
- `web/src/i18n/language-context.tsx` — context + localStorage binding.
- `web/src/i18n/dictionary.ts` — `DICT = { vi: {...}, en: {...} }` with `satisfies` type guard.
- `web/src/labels.ts` — `labelFor(map, key, t?)` helper; format functions (`formatDateTime`, `formatCost`, etc.) always Vietnamese.
- Components in Canvas (r3f) receive `t` via props (can't use context inside Canvas).

**Enforcement**: `formatDateTime()` always "HH:mm dd/MM" (vi-VN locale). `formatCost()` always "$X.XX" (USD). Both hardcoded, not translated.

### 5.7 Motion & a11y

- **Transitions**: button/nav/tab/chip hover = 120–180ms smooth (no jarring jumps).
- **Confirm dialog**: fade-in 200ms.
- **Respects `prefers-reduced-motion`**: all transitions gated → `no-preference` only.
- **Reduce mode**: transitions stripped entirely (no-op CSS).
- **Focus management**: modal trap focus, Escape closes, scroll-into-view on keyboard nav (ConfirmDialog accessibility).

### 5.8 UI Mode: Dual-layer view toggle (v10 M25)

**Concept**: Low-tech CEO mode vs. high-tech advanced mode, toggled globally via `ui-mode-context.tsx`.

**Behavior**:
- **Low** (default): CEO 4-item nav (Team/Chạy tay/Cài đặt/Tài liệu); advanced views hidden.
- **High**: Full nav (low 4 + Overview/Dòng thời gian/Chi phí/Bộ nhớ/Guardrail/Cấu hình/Chạy tay thủ công); all 7 advanced views rendered.
- **Persistence**: `localStorage['ui-mode']`.
- **Localization**: All 7 advanced views + 5 components translated to Vietnamese (labels.ts, no English leak).

**Files**:
- `web/src/ui-mode-context.tsx` — manages `ui-mode: "low" | "high"`, provides hook.
- Settings → "Chế độ hiển thị" toggle → calls context setter.
- Routes for advanced views check context; hidden in low mode but still navigable via direct URL (auth remains the true boundary).

### 5.9 Chart theme-awareness (v10 M24–M25)

**Before**: hardcoded colors (hex literals), ignored theme.
**After**: Charts read design tokens via `getComputedStyle()`, remount on theme change.

**Files**:
- `web/src/components/charts/chart-theme.ts` — `getChartColors()` reads computed `--color-{status}` values, returns chart.js dataset config.
- Components use `key={resolvedTheme}` to remount when theme flips → refetch colors.

### 5.10 Responsive design (v9 M4 + v54)

**Mobile-first card-list**: `@media (max-width: 640px)` transforms CEO tables (Team/Tasks/Approvals) into card layouts:
- `<tr>` → card div; `<td>` → flex row with `data-label` label prefix.
- CEO personas (low-tech non-technical): card easy to scan on phone.
- Advanced personas (AuditTable/RunList/Overview): `.table-scroll` overflow-x (technical users expect horizontal scroll).

**Touch-friendly**: `min-height: 44px` for buttons; `font-size: ≥16px` on inputs (iOS Safari zoom prevention).

**Wrap**: nav, quick-action chips, approval lists wrap on mobile.

### 5.11 Office Cockpit Layout (v54)

**3-zone grid design** (`web/src/views/office-unified/`): Fixed left action rail (260px) + center canvas/feed + right column (≤300px) + full-width composer. Layout shifts to single-column stacking (rail-first) at ≤1100px viewport.

**Left rail primitives:**
- **"Chờ anh/chị" queue:** Merged approval + clarify items (approve/reject + answer in place), shared `useSharedPendingApprovals` + `getClarifyPending` endpoints. Empty state shows one ✓ check mark.
- **"Sắp chạy" schedule:** GET `/api/schedule/upcoming` (service EFFECTIVE schedule incl. synthesized watch tasks), refreshed every 60s.

**Center columns:**
- **Canvas:** 3D scene (collapsible).
- **Activity feed:** Step + milestone + review + external_action events, filtered by chips [Tất cả | Bước | Ra ngoài] (presentation-only, no re-fetch).

**Right column:**
- **Workroom list + cost chips** (lazy per-room cost via `formatCost`).
- **Outputs:** Completed step artifacts.
- **Review tray:** Click a review line → per-criterion rows (✓/✗ + note), persisted in `captures.criteria_json` (detail endpoint only).

**3D badges:**
- **✋ waiting-hand** on desks with pending approvals/clarifications (coordinator table included).
- **×N fan-out count** when ≥2 concurrent steps.
- **Translucent ghost figure** while deep_team step runs (step events carry `deep_team` flag).

## 6. Giọng UI (v9 M1)

**i18n approach**: Centralized `web/src/labels.ts` (DRY):
- `KIND_LABEL`, `RUN_STATUS_LABEL`, `VERDICT_LABEL` — enums → Vietnamese labels.
- `formatDateTime(date)` — ISO → "HH:mm dd/MM" Vietnamese format.
- `formatCron(cron_string)` — "0 9 * * 1,3" → "09:00 Thứ 2, Thứ 4".

**Trust surface (v9 M1)**: `action-summary.ts` translates Lớp B actions to human-readable Vietnamese:
- Jira create/close/transition/assign.
- Slack post internal/external.
- Confluence createPage.
- Linear comment, GitHub PR merge/close.
- Email send (recipient/subject visible).

**External flag**: actions with `class="confirm-external"` highlighted red/bold + warning "Gửi RA NGOÀI công ty". JSON audit always available in `<details>`.

## 7. Unresolved / Next

- Chế độ Dark/Light theme trở thành default user preference thay vì opt-in (M24 hoàn tất).
- Android/Linux deployment via Docker Compose (v10 M26 deferred: macOS-only install.sh stable).
- Multi-user session + SSO (chưa scope — currently single-user CEO mode).
