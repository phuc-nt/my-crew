# HANDOVER — my-project-manager

Bạn là agent/đội mới nhận repo này để **refactor + phát triển tiếp**. File này là điểm
vào DUY NHẤT: đọc xong bạn biết đọc gì tiếp. Không cần biết toàn bộ quá trình xây dựng —
chỉ cần đủ context để làm tiếp an toàn.

---

## 1. Sản phẩm là gì (30 giây)

Một **đội nhân sự ảo AI** cho công ty một-người. CEO (không kỹ thuật) giao việc qua web/
Telegram; các agent tự làm việc PM/nội dung/nghiên cứu/phân tích/kiểm định, đọc dữ liệu
thật từ Jira·GitHub·Confluence·Slack, và *tự hành động* (viết báo cáo, tạo trang, cảnh báo).

**Triết lý cốt lõi — thuộc nằm lòng:** *tự chủ về TỐC ĐỘ, không bao giờ tự chủ về TRÁCH
NHIỆM.* Mọi hành động ghi ra ngoài công ty đi qua MỘT cửa kiểm soát (Action Gateway);
việc mất-dữ-liệu/lộ-bí-mật bị chặn cứng, LLM không vượt được kể cả khi "muốn".

## 2. Tech stack

- **Backend**: Python ≥3.12, quản lý bằng **uv**. LangGraph (agent graph). FastAPI + SSE.
  SQLite (WAL) cho state. Không dùng ORM.
- **Frontend**: React 19 + TypeScript + Vite; react-three-fiber/three cho màn 3D "Văn phòng".
  Build dist commit vào `src/server/static/app/` (server serve tĩnh).
- **Tích hợp ngoài**: MCP servers (Jira/Confluence/Slack) + `gh` CLI (GitHub) + `gws` CLI
  (Google Sheets, hr-pack). LLM qua OpenRouter.
- **Test**: `uv run pytest` (~1706 BE) · `cd web && npx vitest run` (~177 FE) · `npx tsc --noEmit`.

## 3. Đọc theo thứ tự này

| # | File | Để biết | Ưu tiên |
|---|------|---------|---------|
| 1 | **`CLAUDE.md`** | Luật làm việc trong repo (workflow, quy tắc code, commit, hook privacy) | BẮT BUỘC |
| 2 | **`.claude/rules/*.md`** | Chi tiết: development-rules, primary-workflow, orchestration, review | BẮT BUỘC |
| 3 | **`docs/project-overview-pdr.md`** | Vision, vấn đề, phạm vi, yêu cầu — VÌ SAO có sản phẩm | BẮT BUỘC |
| 4 | **`docs/system-architecture.md`** | Kiến trúc as-built v18 (sơ đồ, thành phần, luồng dữ liệu) | BẮT BUỘC |
| 5 | **`docs/action-gateway-explainer.md`** | Mô hình an toàn (Action Gateway) — trái tim sản phẩm | BẮT BUỘC |
| 6 | **`docs/codebase-summary.md`** | Bản đồ "cái gì ở file nào" + quyết định theo mốc | BẮT BUỘC |
| 7 | `docs/uat-theo-user-story.md` | Sản phẩm LÀM ĐƯỢC GÌ (7 epic, 22 story) — spec hành vi | Cao |
| 8 | `docs/project-roadmap.md` | Đã làm gì + việc nên làm tiếp | Cao |
| 9 | `docs/deployment-guide.md` | Cài / chạy / backup | Khi deploy |
| 10 | `docs/code-standards.md`, `docs/design-guidelines.md` | Chuẩn code + UI | Vừa |
| 11 | `docs/journals/*`, `plans/*` | Lịch sử từng vòng — chỉ tra khi cần "vì sao quyết định X" | Tra cứu |

> `README.md` cho người học "cách build agent có guardrail" (vision, không phải map kiến
> trúc hiện tại). `docs/huong-dan-su-dung.md` là hướng dẫn tiếng Việt cho CEO (người dùng
> cuối). `docs/archive/` chứa tài liệu cũ (v1/v2, phỏng vấn, so-sánh-kiến-trúc) — CHỈ tra
> khi cần lịch sử.

## 4. Bản đồ code (nơi bắt đầu khi sửa)

```
src/
  agent/        LangGraph graphs + nodes. LÕI: coordinator_graph.py (ticker điều phối),
                team_task_graph.py (chạy 1 bước việc), task_decomposition.py (chia việc),
                review_graph.py (soát chéo), ops_*.py (lệnh CEO: giao/chỉnh việc)
  actions/      Action Gateway (action_gateway.py) + hard_block.py (Lớp A chặn cứng) +
                *_write.py (handler ghi ngoài, đều qua gateway)
  runtime/      service.py (daemon điều phối/scheduler), worker.py (chạy 1 agent),
                team_task_store.py (SQLite state đội), office_room_*.py (feed realtime)
  server/       FastAPI app.py + routes_*.py + office_event_projection.py (PII firewall)
  llm/ config/ profile/ skills/ packs/ company_docs/ reporting/ audit/  — hỗ trợ
web/src/
  views/office-unified/  Màn chính "Văn phòng" (3 cột: phòng việc | hoạt động | kết quả)
  views/office-3d/       Cảnh 3D (r3f), reducer sự kiện → trạng thái bàn
  views/                 Team, Work (Duyệt), Settings, Chat…
```

Entry points: web `python -m src.server.app` (hoặc `main()` trong app.py) · daemon điều
phối `python -m src.runtime.service` · CLI `python -m src.entrypoints.mpm`.

## 5. BẤT BIẾN — đừng phá khi refactor (đọc kỹ)

Đây là các ràng buộc an toàn đã được red-team + E2E bảo vệ qua nhiều vòng. Sửa mà không
hiểu chúng = tạo lỗ hổng. Chi tiết trong codebase-summary "THE INVARIANT":

1. **Action Gateway = cửa DUY NHẤT ra ngoài.** Mọi ghi external (Slack/Jira/Confluence/
   email) qua gateway → allowlist default-deny + Lớp A hard-block. Thêm handler ghi mới
   PHẢI đi qua đây, không đi tắt.
2. **Ghi ra ngoài = Lớp B (chờ CEO duyệt).** Không tự chạy trừ khi trust-ladder bật.
3. **PII firewall cho office events** (`office_event_projection.py`): allowlist theo kind
   AT WRITE TIME. Không nhét nội dung tự do (tài liệu, câu trả lời đầy đủ) vào room event.
4. **Hash-bind khi giao/chỉnh việc**: CEO xác nhận kế hoạch → hash khóa; `_verify_plan_hash`
   băm lại mỗi tick chống tamper. `room_id`/`pic_id`/`acceptance` là METADATA NGOÀI hash
   (nếu thêm field vào step, hỏi: "nó có va vào hash-check này không?").
5. **Cross-process isolation (khóa từ v12)**: KHÔNG chạy orchestration graph xuyên process.
   Điều phối = ticker (poll ngắn/1-hành-động/thoát) + store + lease. Không nhúng ticker
   vào web app.
6. **registry.yaml = USER-DATA (gitignored từ v18)** — KHÔNG BAO GIỜ `git checkout
   registry.yaml` / không add. Template committed là `registry.example.yaml`.

## 6. Quy trình làm việc (repo dùng skill-driven workflow)

Repo này phát triển theo vòng: **brainstorm → plan → red-team plan → cook (implement) →
review → E2E thật (browser + LLM thật) → docs/journal → commit**. Bằng chứng: `plans/` +
`docs/journals/`. Bạn KHÔNG bắt buộc theo hệt, nhưng 2 điều nên giữ:
- **Red-team plan TRƯỚC khi code** — nhiều Critical được bắt ở tầng plan (rẻ), xem các
  report `plans/*/reports/from-code-reviewer-to-planner-*`.
- **E2E trên đường thật** — "suite xanh ≠ chạy được" đã xảy ra 2 lần (feature dead dù
  test xanh vì test tự set điều kiện prompt/đường thật không tạo ra). Test bằng browser +
  ticker + LLM thật, soi DB.

## 7. Chạy thử tại chỗ

```bash
uv sync
cd web && npm install && npm run build && cd ..     # build FE (dist đã commit sẵn)
PORT=8765 uv run python -c "from src.server.app import main; main()" &   # web
uv run python -m src.runtime.service &                                   # điều phối
# mở http://127.0.0.1:8765  (auth OFF khi localhost + chưa đặt password)
```

Cần data + đội mẫu để thử ngay: `scripts/demo-mode.sh on` (tắt: `off` — trả data thật
nguyên vẹn). Đội thật cần ≥1 coordinator + vài agent office trong `registry.yaml` +
service chạy, nếu không màn Văn phòng hiện banner đỏ "bộ điều phối chưa chạy".

## 8. Nợ kỹ thuật & việc nên làm tiếp (bàn giao trung thực)

- **`docs/codebase-summary.md`** phần thân vẫn dài theo dòng lịch sử v1→v18 — bản đồ
  chính xác nhưng nên gộp phần cũ thành mục ngắn (header đã đồng bộ v18).
- **Cải thiện đã ghi nhận từ UAT v17/v18** (chưa làm): xem
  `plans/260711-0711-.../reports/uat-260711-0908-*findings*.md` + `docs/project-roadmap.md`
  §"Việc nên làm tiếp" — vd hr/sales-pm là hồ sơ agent mồ côi chưa đăng ký; web_search cần key.
- Nhật ký/plan rất nhiều (67 journal, 22 plan) — là lịch sử, KHÔNG cần đọc để làm tiếp;
  tra khi cần "vì sao quyết định X".

## 9. Không được làm

- Không commit secrets/.env/token/private key/db creds/personal data.
- Không sửa skills trong `~/.claude/skills` (sửa bản trong repo nếu được yêu cầu).
- Không dùng prefix `chore`/`docs` cho commit thay đổi thư mục `.claude/`.
- `company.yaml`, `.data/`, `registry.yaml`, hồ sơ trong `profiles/<id>` = user-data
  (gitignored) — không commit.
