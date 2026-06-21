# Code Standards — my-project-manager

> Quy ước code. Status: **Initial 2026-06-21**. Cập nhật khi convention thật hình thành.

## Ngôn ngữ & stack

- **Python 3.12+**, **LangGraph** là lõi orchestration.
- Dùng `uv` hoặc `pip` + `pyproject.toml` (agent build chọn, ghi lại quyết định ở đây).
- Lint: `ruff` (clean trước commit). Type hint bắt buộc cho public function.

## Naming

- File/module Python: `snake_case`, tên mô tả dài cũng OK (self-documenting cho Grep/Glob). Vd `jira_read.py`, `action_gateway.py`.
- Class: `PascalCase`. Hàm/biến: `snake_case`. Hằng: `UPPER_SNAKE`.
- Tránh tên mơ hồ (`utils.py`, `helpers.py` chung chung) — đặt theo concern.

## Cấu trúc & modularization

- File > ~200 dòng → cân nhắc tách. Check module có sẵn trước khi tạo mới.
- Tách theo concern: tool READ (`tools/`), WRITE (`actions/`), graph (`agent/`), llm (`llm/`).
- 1 module tool = 1 công cụ. KHÔNG trộn Jira + GitHub trong 1 file.

## Quy tắc riêng dự án (quan trọng)

1. **KHÔNG gọi API write trực tiếp** từ node/tool. Mọi mutation qua `actions/action_gateway.py`. Vi phạm = bug nghiêm trọng (phá guardrail "full autonomous").
2. **Tool trả dữ liệu chuẩn hóa**, không trả raw API response cho LLM. Chuẩn hóa ở tool layer.
3. **Mọi write log audit** trước khi return. Không audit = không được merge.
4. **Secrets chỉ qua env**. Hardcode token/key = chặn merge. `.env` không commit; cập nhật `config.example.env`.
5. **Errors tường minh** — try/except phải log + raise có ngữ cảnh, KHÔNG nuốt lỗi im lặng.
6. **Bounded I/O** — mọi call ngoài có timeout + retry giới hạn (chống treo agent).

## LLM / prompt

- Prompt để trong `llm/` (hoặc file riêng), KHÔNG rải rác inline khắp code.
- Provider-agnostic: không khoá cứng 1 nhà cung cấp ở tầng graph.
- **Provider = OpenRouter** (OpenAI-compatible, `base_url=https://openrouter.ai/api/v1`). Model qua env `OPENROUTER_MODEL`, default `minimax/minimax-m2.7`, fallback `qwen/qwen-3.7`. Đổi model KHÔNG sửa code — chỉ env.
- Set header `HTTP-Referer` + `X-Title` cho OpenRouter call.
- Mọi LLM call: token/cost ý thức được (log usage khi có thể) — quan trọng vì autonomous loop có thể đốt tiền.

## Testing

- Test trước khi push. KHÔNG ignore test fail để build xanh.
- KHÔNG fake data/mock để giả pass. Mock chỉ dùng để **cô lập external API** trong unit test, phải rõ ràng là mock.
- Tool layer thiết kế để mock được (cho test không cần API thật).
- Chạy compile/import check sau khi sửa code.

## Git

- Conventional commits: `feat:`, `fix:`, `refactor:`, `test:`. KHÔNG ref AI trong message.
- KHÔNG `chore`/`docs` prefix cho thay đổi file `.claude/`.
- KHÔNG commit secrets (`.env`, token, credential). Kiểm file list trước commit.
- Xác nhận với chủ dự án trước khi push / thao tác khó đảo ngược.

## Nguyên tắc

- **YAGNI · KISS · DRY** — thứ đơn giản nhất chạy được.
- Code đọc như code xung quanh (match style, comment density).
- Comment cho logic phức tạp; code tự giải thích cho phần đơn giản.
