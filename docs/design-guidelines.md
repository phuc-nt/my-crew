# Design Guidelines — my-crew

**Status:** Updated 2026-08-19 (v87 web FE redesign: 5-hub IA, TanStack Query, `/features/` structure).

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
| **ProgressBar** (v93) | `<ProgressBar value tone label>` | `.progress`, `.progress-fill`, `.progress-{tone}` | Ratio 0–1 as a filled track; `role="progressbar"` + aria values. Tone follows the same ok/warn/danger scale as Badge. |
| **StatTile** (v93) | `<StatTile label value badge footer>` | `.stat-tile`, `.stat-tile-value`, `.stat-tile-footer` | One headline number + caption for dashboard heroes. Never a Card-in-Card. |

**Header rule (v53)**: New view styles MUST extend these primitives (6 from v53 + ProgressBar/StatTile from v93). Visuals stay in `App.css` section 3 (PRIMITIVES), behaviors in React. DISALLOWED: `.my-button`, `.card-accent`, `.input-lg` — reuse existing classes or propose token addition.

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

### 5.11 Five-Hub Architecture (v88)

`/` điều hướng sang `/chat` (màn nhà). Năm hub sở hữu mọi màn; route top-level cũ giờ là tab
trong hub.

| Hub | Gốc | Gồm |
|---|---|---|
| Chat | `/chat` | `/chat/:roomId` cho từng phòng việc |
| Office | `/office` | Sàn bàn 3D, activity feed, quick assign |
| Work | `/work` | Board, outputs, company activity; `/work/task/:room` cho chi tiết |
| Team | `/team` | Roster; `/team/:id` cho chi tiết agent (8 tab: profile · activity · knowledge · skills · channels · budget · memory · advanced) |
| System | `/system` | Settings · connections · company · insights · audit |

**URL cũ**: 21 redirect, có e2e phủ — `/assistant`, `/settings`, `/connections`,
`/company-docs`, `/captures`, `/outputs`, `/company-activity`, `/approvals`, `/tasks`,
`/create`, `/agents/:id`, `/overview`, `/timeline`, `/cost`, `/memory`, `/guardrail`,
`/config`, `/trigger`, `/office/timeline`, `/office/3d`, và mọi path lạ → `/chat`.

**Tab nằm ở URL** (`?tab=`), nên deep link mount đúng tab khi cold load.

### 5.12 Office Layout (v54 → v88)

Sàn bàn ở `web/src/features/office/`. **Action rail cố định bên trái của v54 đã bỏ**: hàng đợi
duyệt giờ là một query cache mà `/work` sở hữu, `/office` giữ đúng phần nó làm tốt nhất — canvas
3D + activity feed + quick assign. Bố cục dồn về một cột ở ≤1100px.

- **Activity feed:** sự kiện step + milestone + review + external_action, lọc bằng chip
  [Tất cả | Bước | Ra ngoài] (thuần trình bày, không re-fetch).
- **Desk inspector:** click một bàn → trust mode, budget, tool call đang chạy, cost
  (`formatCost`). v88 inspect tại chỗ thay vì điều hướng đi như màn cũ.
- **Quick assign:** mở đúng `AssignComposer` của hub chat trong dialog, không dựng composer
  thứ hai.

**Huy hiệu 3D** (`office-3d/desk-badges.tsx`, overlay `<Html>` của drei):
- **✋** trên bàn có việc chờ duyệt / chờ trả lời (gộp từ approvals index + clarify questions
  qua `derivePendingCounts`).
- **×N** khi ≥2 bước chạy song song.
- **Bóng mờ trong suốt** khi bước deep_team đang chạy (event step mang cờ `deep_team`).

### 5.13 Dashboard, attention center, shortcuts (v93 — openhuman-inspired)

Ideas borrowed from openhuman's UI (GPL — patterns only, no code): a cost dashboard with a
hero number, a severity-ordered notification center, and a `?` shortcuts sheet.

**Số liệu tab** (`web/src/features/system/insights-*.tsx`):
- **Hero first**: fleet spend / cap / % as three `StatTile`s + one `Badge` (ok/warn/over at
  80 % and 100 %) + one `ProgressBar`. Detail tables (per engine, per tool, routing funnel)
  come after the hero, never above it.
- **Freshness line**: "Cập nhật Ns trước" + a *Làm mới* chip that refetches every insights
  query at once. The window selector writes `?days=` to the URL so a view is shareable.
- Empty stores render the hero with zeros; no spinner-forever, no 5xx on a fresh install.

**Attention center** (`web/src/features/attention/`, bell in the header):
- One list, ordered `error > warning > info`, stable within a band. Sources: coordinator
  heartbeat, stalled cards, budget ratio (≥1 error, ≥0.8 warning), team alerts, pending
  approvals, clarify questions, template upgrades.
- The **badge counts error + warning only**; info never nags. The `/work` nav badge keeps
  counting approvals independently — two badges, two questions ("what needs me" vs "how
  many approvals").
- Every item is a `Link` deep link (`/system?tab=settings`, `/work/task/:room`,
  `/team/:id?tab=budget`, …); clicking navigates *and* closes the panel.
- **Dismissal is per fingerprint**, stored in `localStorage` (`my-crew.attention.dismissed`):
  the same alert with a changed message (or a budget that crosses the next band) comes back.
  *Đã xem tất cả* dismisses everything currently listed and prunes stale entries.
- The bell sits **outside** `.app-header-actions`, so on mobile it stays visible while the
  mode / language / theme chips fold into the overflow menu. The panel goes fixed-width on
  ≤640 px.

**Keyboard** (`web/src/features/palette/shortcuts-help.tsx`): `?` toggles the shortcuts
sheet, `g` then `c/o/w/t/s` jumps to a hub (1 s chord window), `⌘K`/`Ctrl+K` opens the
palette. Chords ignore editable targets and any modifier; Escape closes. The ⌨ header chip
opens the same sheet for mouse users.

### 5.14 Pre-authorization, resilience, onboarding (v94–v96 — openhuman-inspired)

Second round of openhuman patterns (still ideas only, GPL): pre-authorize once, keep the
app standing when one screen dies, fold noise, and make the first visit self-explaining.

**Pre-authorization card** (`web/src/features/shared/preauth-card.tsx`, in the assign
composer next to the plan preview):
- Rendered from the preview's `manifest` (`my_crew/server/assign_manifest.py`), which is
  read from the persisted draft rows the confirm will bind — never from the preview text —
  so the card and the run cannot disagree. No external step → no card.
- Two answers: *Duyệt tất cả* for this task (`preauth_scope: once`) or as a standing
  policy (`always`). The scope travels on the confirm call and is stored only after the
  confirm succeeded; it never enters `plan_hash`.
- Runtime honours it in the ticker after the learned-rule block: a DENY rule and
  `require_ceo_approval` always win. `always` learns the real queued action as an ALWAYS
  rule in the assignee's store, so the next task of the same kind never asks.

**Composer queue + todo strip** (`shared/composer-queue.ts`, `chat/thread-todo-strip.tsx`):
follow-ups typed while busy are queued and flushed in order; the strip is derived from the
room artifact index, so it needs no new endpoint. **Failure guidance**
(`shared/failure-guidance.ts`): one pure map from failure mode → "vì sao / làm gì tiếp",
reused by the task card, task detail and the interrupted-answer card.

**Resilience** (`app/app-error-boundary.tsx`, `app/update-available-banner.tsx`,
`work/control-plane-overview-strip.tsx`):
- The boundary is keyed by route: navigating away resets it, the header and nav stay
  usable, and the card offers retry or reload.
- The banner compares `/health.version` (polled once a minute) with the version the
  bundle started with; it only ever offers "tải lại", never auto-reloads.
- The strip is the four control-plane counters plus a coordinator badge, refreshed by the
  SSE bridge — the same numbers `mpm crew overview` prints.

**Folding noise in the thread** (`chat/background-activity-drawer.tsx`,
`chat/interrupted-answer-card.tsx`, `shared/citation-chips.tsx`): activity lines collapse
behind one row that shows the newest inline; a failed step becomes one card with draft,
error, guide and retry, and leaves once the step runs again; citations are read out of
the text itself (one chip per host, outbound, `rel="noopener"`).

**Onboarding** (`web/src/features/onboarding/`):
- `AppWalkthrough` is four steps anchored via `data-walkthrough` attributes on the real
  elements (nav, composer, bell, ⌨ button) and a single outline class; it opens once
  (`my-crew.walkthrough.done`), and the ⌨ sheet can replay it through a window event.
- `PageWelcome` replaces the muted empty line on the overview, board and roster. Its three
  example briefs seed the composer: in place on the chat hub, via router state elsewhere.
- Keep both out of e2e by default: the Playwright mock plants the done flag unless a test
  opts in with `walkthrough: true`.

**Resizable panes** (`chat/resizable-panes.tsx`): grid columns are CSS variables set from
persisted widths; the handles sit in the grid gap, are keyboard-operable (`role=separator`,
arrow keys, `aria-valuenow`) and clamp to per-pane limits. Below 1100 px the pending pane
handle disappears with the pane; below 900 px both do.

**Contextual palette rows** (`palette/contextual-commands.ts`): a pure map from the current
path to rows shown first with the hint *Ở đây*; nav, command and history rows follow.
**Snooze** (`attention/snooze.ts`): stored apart from dismissals as `{id: {fingerprint,
until}}`; the centre arms one timer for the next expiry and prunes entries whose alert
changed or expired.

## 6. Code Organization — Feature-Based Modules (v88)

**From `/views/` to `/features/`**: component hierarchy is hub-centric, not view-centric. Each hub gets a top-level folder:

```
web/src/features/
├── chat/          # Chat hub: conversation list, message composer, thread detail
├── office/        # Office hub: 3D workspace, workroom list, action queue
├── work/          # Work hub: approvals queue, kanban board, task detail, outputs, schedule
├── team/          # Team hub: roster, agent detail with 8 tabs, hire panel
├── system/        # System hub: settings, connections, company, insights, audit
├── shared/        # Used by more than one hub: assign composer, artifact viewer,
│                  #   transcript tab, coordinator health banner, office message line
├── palette/       # Command palette (Cmd+K), shortcuts sheet, contextual rows — not a hub
├── attention/     # Attention bell: item builder, dismiss + snooze state, centre panel
└── onboarding/    # First-visit walkthrough + per-hub welcome card
```

`web/src/views/` keeps only the pre-auth doors (Login, Setup) — they mount outside the
hub shell, so they belong to no hub.

**Lazy loading** — expensive subtrees load on demand:
- Agent detail page: 8-tab component (charts, editor, telegram config) → lazy chunk
- Task detail page: artifacts + transcript viewer → lazy chunk
- Office 3D scene → lazy chunk (react-three-fiber, three.js)

**Data layer** (`web/src/api/queries/`):
- `query-keys.ts` — single factory for React Query cache key generation; gates SSE→invalidate bridge
- Per-hub files: `use-office-queries.ts`, `use-work-queries.ts`, `use-team-queries.ts`, `use-system-queries.ts`, `use-agent-detail-queries.ts`
- Global: `use-agents-queries.ts`, `use-approvals-queries.ts`, `use-artifact-queries.ts`, `use-clarify-queries.ts`, `use-auto-approved-query.ts`
- SSE bridge: `sse-invalidation-bridge.ts` — listens to office events, invalidates affected cache keys

**API client** (`web/src/api/client.ts`): Thin HTTP wrapper, no caching logic (TanStack Query owns that).

## 7. Giọng UI (v9 M1 + v87 redesign)

**i18n approach**: Centralized `web/src/i18n/dictionary.ts` + `web/src/labels.ts` (DRY):
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

## 8. Unresolved / Next

- Chế độ Dark/Light theme trở thành default user preference thay vì opt-in (M24 hoàn tất).
- Android/Linux deployment via Docker Compose (v10 M26 deferred: macOS-only install.sh stable).
- Multi-user session + SSO (chưa scope — currently single-user CEO mode).
