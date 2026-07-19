# v53 — UI kỷ luật + song ngữ: primitives, format chuẩn, language mode VN/EN

**Ngày:** 2026-07-19 · **Commits:** 8 (P1 nền → P2 a/b/c quét → P3 infra → P4 a/b i18n → P5 fix+docs) · **Suite:** 2370 BE + 221 FE · **Plan:** `plans/260719-0723-ui-consistency-language-mode/`

## Bối cảnh & quyết định

Audit lộ App.css 767 dòng xếp theo niên đại → drift: 8 kiểu button + 65 nút trần, 5 card/4 table/3 empty-state, cost 2-vs-4 lẻ ở 7 chỗ, 2 format giờ, 3 token ma (`--color-err` không đảo dark-mode), nav trộn "Captures" EN. CEO chốt: primitives + quét toàn bộ; giữ 1 App.css sắp theo concern; **thuật ngữ kỹ thuật giữ EN + thêm language mode VN/EN**; formatCost 4-lẻ-dưới-$1.

## Đã làm

- **P1 nền:** fix token ma, token hóa radius/hex (thêm `--radius-sm`), App.css 5 section cứng + quy tắc "không chế class mới"; 6 primitive (`components/ui/`: Button/Card/Badge/Input/EmptyState/PageHeader — wrapper mỏng trên class CSS chuẩn, không CSS-in-JS); `formatCost`.
- **P2 quét (3 batch subagent, commit theo loại):** 1 format cost/date + 16 EmptyState; 65 button → primitive (28 giữ raw có lý do: container-selector/segmented/list-item — ghi chú unify-later); Card/PageHeader ~20 view + 1 chuẩn table + xóa CSS chết (badge-on/off/trust-*, office-header).
- **P3 infra song ngữ:** `i18n/` LanguageContext (localStorage, default vi) + dictionary typed-keys — **vi là nguồn key, `en satisfies` → thiếu key = lỗi compile** (type system làm test i18n-completeness, 0 thư viện ngoài); chip VN/EN cạnh lens+theme.
- **P4 quét i18n (2 batch):** ~60 file, mọi string tĩnh FE vào dictionary 2 ngôn ngữ; labels.ts maps song ngữ; `friendlyError` đọc lang từ localStorage (tầng không có React context); **component trong Canvas nhận `t` qua props** (r3f render ngoài cây context). Ranh giới giữ đúng: string backend + nội dung LLM = data, vẫn VN ở EN mode.
- **P5 UAT browser thật:** 6/6 PASS — EN trọn chrome+views, Outputs còn VN đúng-chỗ-data, strip live formatCost chuẩn, badge pill duy nhất 999px; **bắt 1 bug thật: tràn ngang 480px** (hàng 5 toggle không wrap sau khi thêm chip VN/EN) → fix tại chỗ.

## Vấp & học được

- **`*/` trong comment CSS**: header rule tôi viết chứa `--space-*/--fs-*` — chuỗi `*/` đóng comment sớm, minifier gãy với lỗi khó hiểu (`Delim('*')` ở dòng khác). Comment CSS không được chứa `*/` dù trong "văn xuôi".
- **Perl `$1{...}` = hash element**, không phải backreference + literal — sed đa dòng phức tạp chuyển sang python cho lành.
- **Component trong `<Canvas>` không dùng được context** — thread `t` qua props là pattern đúng cho r3f.
- Test-fix hàng loạt do thiếu provider (47 fail một lúc) — `test-utils.AppProviders` là chỗ thêm provider mới, các test wrap tay phải theo.
- Subagent bắt được premise sai của controller (`.advanced-bar` không phải h2+actions) và xử lý theo intent — prompt nên nói mục tiêu, không chỉ cơ chế.

## Còn treo

- 12 nút raw styled qua container-selector (setup/agent-actions/login…) — unify pass sau (đã comment trong code).
- `Approvals.tsx` dead code (không còn route) — dọn đợt sau.
- CEO restart web live để nạp bundle mới + mắt thường soát EN mode 1 vòng.
