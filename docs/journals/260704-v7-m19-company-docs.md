# v7 M19 — Company Docs: kho tài liệu chung cho mọi agent

2026-07-04 · ✅ Done

Tính năng MỚI duy nhất của v7 (còn lại là mặt tiền). CEO paste tài liệu công ty (quy trình, chính sách, danh bạ) vào kho chung → tick cho agent nào đọc → agent trả lời/làm việc dựa trên tài liệu đó. INTERNAL-only tuyệt đối: báo cáo ra ngoài không bao giờ chứa.

## Tên: "Company Docs" (KHÔNG dùng "knowledge")
Chữ "knowledge" đã bị M18b chiếm (tab Kiến thức = form SOUL/PROJECT + skills từng agent). Chủ dự án chốt tên riêng cho kho chung → **Tài liệu công ty** (dir `company-docs/`, block prompt `<company_docs>`, module `src/company_docs/`). Tách bạch tuyệt đối để không lẫn hai khái niệm.

## Làm gì
- **store** (`company_docs/store.py`): file phẳng `company-docs/<slug>.md` (frontmatter title/updated), CRUD atomic (.tmp→replace), MAX_DOC_CHARS 50KB reject-not-truncate, slug regex `^[a-z0-9][a-z0-9-]*$` chống path-escape. KHÔNG DB, KHÔNG RAG (kho nhỏ, opt-in per-agent là đủ — YAGNI).
- **inject** (`company_docs/inject.py`): `company_docs_text(context, audience)` — guard `audience != "internal" → ""` (byte-for-byte cơ chế `select_skill_text`). `render_company_docs` bọc `<company_docs>` bounded MAX_INJECT_CHARS 12KB, cắt theo RANH GIỚI tài liệu + khai báo "[đã lược bớt]" (không cắt im lặng). KHÔNG selector LLM như skills — CEO đã tick = đã chọn, inject hết (bounded).
- **pool** (`company_docs/pool.py`): resolve slug list → CompaDoc, slug lạ/hỏng → drop + warn (không crash run).
- **loader seam**: `LoadedProfile.company_docs: tuple[str,...]` + parse (mirror `skills`); wire vào `ProfileContext.company_docs` ở 3 build site (worker/cli/cron) qua `load_company_docs(getattr(loaded,"company_docs",()))`.
- **inject vào 3 builder + Q&A**: report/okr/resource prompt builder thêm param `company_docs` chèn SAU skills TRƯỚC siblings, CHỈ nhánh internal; Q&A (`qa_answer`) render docs (internal-only path, không có biến thể external).
- **routes**: `routes_company_docs.py` (library CRUD, create-collision 409, oversize 400) + `routes_agent_company_docs.py` (opt-in per-agent, ghi `company_docs:` vào profile.yaml, slug lạ 400). Auth-gated (không public).
- **UI**: `CompanyDocs.tsx` (kho: list + editor textarea + xóa confirm) + `CompanyDocsPicker` trong tab Kiến thức trang agent (tick per-agent). Nav thêm "Tài liệu".
- **backup.sh**: +`company-docs/` vào tar. `.gitignore`: `company-docs/` (user data, restore từ backup, không commit).

## THE RED LINE (external = 0) — mutation-proven
Mọi đường inject đều qua guard `audience != "internal" → ""`. Test 2 lớp trên CẢ 3 builder: internal có sentinel, external KHÔNG có sentinel VÀ không có tag `company_docs`; `company_docs=""` → prompt BYTE-IDENTICAL (backward-compat). Q&A path internal-only (không có biến thể external — reply mention vào kênh nội bộ loader-guaranteed). External branch lấy KHÔNG GÌ từ profile (kể cả persona) — defense-in-depth Phase-5.

## Review: red line HELD, 1 MEDIUM vá
- **Red line HELD (CONFIRMED)**: reviewer trace cả 3 builder (internal+external) + graph wiring + Q&A → external nhận 0 byte tài liệu. Không CRITICAL/HIGH.
- **MEDIUM (vá): VN slug → "doc"**: `slugify` regex ascii-only làm mọi tiêu đề tiếng Việt ("Chính sách", "Quy trình") collapse thành "doc" → tài liệu VN thứ 2 collide 409, CEO không tạo được. Sản phẩm Việt-first = bug thật. Vá: fold dấu (đ→d rồi NFKD strip combining) TRƯỚC slugify → "quy-trinh-nghi-phep". Test: VN titles ra slug riêng biệt; `日本語` → "doc" (fallback).
- MEDIUM (giữ, pre-existing): PUT profile strip YAML comment — y hệt M18b skills picker (đã ship), không phải regression M19; theo luật "không đảo pattern đã verify" → giữ.
- LOW: inject budget "mềm" (~2 char/doc + marker ~55 char không tính vào `used`) — bounded overshoot vô hại, không off-by-one (doc đầu luôn emit, không bao giờ block rỗng).

## Verified
1140 pytest (+39 M19: store CRUD/slug/oversize, inject bounded/red-line, pool drop-stale, routes CRUD/collision/opt-in, 3-builder mutation external=0) + 50 vitest (+3 CompanyDocs library) + ruff + tsc + build. **E2E LIVE data thật** (agent hr/sales-pm, non-destructive restore): paste "quy trình nghỉ phép" → tick HR → HR internal prompt CÓ "12 ngày phép", HR external prompt SẠCH, PM (không tick) KHÔNG mang; verify qua real loader→pool→inject→builder. Dọn sạch.

## Bài học
- **Red line tái dùng = copy CẢ guard, không chỉ pattern**: `company_docs_text` dùng ĐÚNG điều kiện `audience != "internal"` như `select_skill_text` → nếu builder lỡ forward string, string đã "" cho external. Guard ở NGUỒN, không phải ở mỗi call site.
- **Inject-all-ticked đơn giản hơn LLM-select**: skills cần selector LLM (chọn skill hợp báo cáo); knowledge CEO đã tick = đã chọn → render hết + bounded. Ít code hơn, ít token hơn, đủ dùng. YAGNI: RAG là chuyện khi kho phình.
- **Tên là quyết định thiết kế**: "knowledge" đã có nghĩa khác (M18b) → đặt tên mới ("Company Docs") tránh lẫn cho CEO + tránh collision file/route. Hỏi chủ dự án trước khi chọn thay vì tự đoán.
- **Sản phẩm Việt-first: slug phải fold dấu**: ascii-only regex là bug im lặng cho tiếng Việt (mọi tiêu đề → "doc"). Reviewer bắt vì test với title thật, không phải "leave-policy".

## Unresolved / next
1. M20: CEO-first nav 4 mục (Trợ lý/Đội/Việc/Cài đặt) — gom nav 12 mục hiện tại; "Tài liệu" + trang agent vào đúng nhóm.
