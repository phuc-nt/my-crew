# my-crew

[![ci](https://github.com/phuc-nt/my-crew/actions/workflows/ci.yml/badge.svg)](https://github.com/phuc-nt/my-crew/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/my-crew)](https://pypi.org/project/my-crew/)

*[English](README.md)*

Một **agent tự chủ trên LangGraph (Python)** làm phần việc **quản lý** lặp đi lặp lại (PM / Scrum Master / Trưởng nhóm) cho đội AI-native — nó đọc trạng thái dự án qua **Jira · GitHub · Confluence · Slack**, suy luận, rồi *hành động* (viết báo cáo, cảnh báo rủi ro, theo dõi OKR) theo lịch của chính nó. Không phải chatbot bạn hỏi — mà là agent tự làm.

Điểm thú vị không nằm ở báo cáo. Mà ở chỗ agent có **toàn quyền ghi tự chủ** mặc định — nhưng vẫn an toàn, vì mọi thao tác ghi đều đi qua một cửa chắn duy nhất: **Action Gateway**.

> **Ý tưởng cốt lõi, một dòng:** *tự-chủ-trước, guardrail khoá cứng, audit đầy đủ.* Mất-dữ-liệu và bảo-mật là lằn ranh đỏ agent **không thể** vượt, kể cả khi LLM "muốn". Tốc độ là mặc định; thận trọng là tuỳ chọn bật một dòng cho từng agent.

## Vì sao có repo này

Đa số dự án "AI agent" gắn tool vào model rồi mong nó ngoan. Repo này làm ngược: **guardrail trước, tự chủ sau** — "tin" được ép bằng kiến trúc, không phải bằng prompt. Ba niềm tin:

1. **Tự chủ là mặc định, không phải phần thưởng.** Agent chạy theo lịch, hành động không cần hỏi; duyệt-trước-khi-ghi là tuỳ chọn bật riêng từng agent.
2. **Có lằn ranh LLM không bao giờ chạm.** Mất dữ liệu, lộ credential, sự cố bảo mật — chặn tại gateway *trước khi* model được hỏi (**Lớp A**), khoá cứng, không prompt hay jailbreak nào với tới.
3. **Harness thật, không phải demo.** Model có tool chưa phải agent. Đây là cả môi trường: scheduler, memory phân tầng, ngân sách, hooks (tường lửa PII + cổng duyệt), audit log bất biến, và Gateway mọi thao tác ghi phải qua.

## Action Gateway (thứ đáng đọc nhất)

Mọi thao tác ghi đi qua một cửa chắn:

```
request → [Lớp A chặn cứng] → [Lớp B: autonomous chạy ngay HAY guarded xếp hàng?]
        → [kill-switch] → [dry-run?] → [rate-limit] → [chống trùng] → [thực thi] → [audit log]
```

- **Lớp A** (lằn ranh đỏ, khoá cứng, không bao giờ tới LLM): mất dữ liệu vĩnh viễn, lộ credential, sự cố bảo mật.
- **Lớp B** (tuỳ chế độ tin tưởng): merge/close PR, đổi người, đăng kênh ngoài — *autonomous* (chạy ngay + audit) mặc định, *guarded* (xếp hàng chờ duyệt) khi bật.
- **Allowlist, không phải denylist:** tool lạ bị chặn mặc định (đổi sau khi red-team tìm ra lỗ bypass của denylist).

Chi tiết đầy đủ: **[docs/action-gateway-explainer.md](docs/action-gateway-explainer.md)**.

## Đã lớn thành gì

Một agent PM (báo cáo ngày/tuần/OKR/nguồn lực) đã thành **một công ty điều hành trọn vẹn qua MỘT cửa chat**: agent **thư ký riêng** trên Telegram lo việc cá nhân của bạn (briefing sáng/tuần, đọc Gmail/Calendar, gửi email, nhắc đúng giờ) *và* giao việc cho cả đội — một câu tiếng Việt thành DAG đa-agent có kiểm chứng, soát chéo theo rủi ro. Bên dưới: nhiều agent độc lập, cockpit trình duyệt, template nhân sự một-click, nhiều tầng runtime (native / tool-calling / deep-agent chạy code THẬT trong Docker sandbox), **trí nhớ bền dùng chung giữa agent**, và **chế độ autopilot** — AI là người quyết cuối: kế hoạch tự xác nhận, task kẹt tự gỡ, việc ghi thường tự duyệt — còn Lớp A + trần chi phí vẫn chỉ người thật đổi được. Bất biến an toàn giữ nguyên qua mọi bước. Lịch sử đầy đủ: **[docs/project-roadmap.md](docs/project-roadmap.md)**.

Từ **0.9.0**, tốc độ là số đo được chứ không phải kỳ vọng: đề khảo sát 5-6 thực thể chạy **11–16 phút, $0.02–0.05/việc** (trước ~40 phút) — dispatch hướng sự kiện (bước sau chạy trong vài giây khi bước trước xong), tier runtime theo từng bước (việc không-tool chạy one-shot), ép tách thu thập song song cho đề nhiều thực thể, và code lấy sẵn dữ liệu search — kiểm chứng qua 12 vòng e2e sống, chuỗi trung thực giữ nguyên (thiếu ghi THIẾU kèm đúng lý do: "web không có" khác "không tới được web").

## Tài liệu

| Để… | Tài liệu |
|---|---|
| **Dùng hệ thống** — cài đặt + vận hành hằng ngày | [huong-dan-su-dung.md](docs/huong-dan-su-dung.md) |
| **Cài + chạy** — bí mật, MCP server, cron | [deployment-guide.md](docs/deployment-guide.md) |
| Hiểu guardrail (bài học chính) | [action-gateway-explainer.md](docs/action-gateway-explainer.md) |
| Vấn đề + tầm nhìn / kiến trúc | [project-overview-pdr.md](docs/project-overview-pdr.md) · [system-architecture.md](docs/system-architecture.md) |
| **Theo dòng phát triển, từng quyết định** | [journals/](docs/journals/) — *quyết gì & vì sao*, *vấp gì & học được gì* |

[Journals](docs/journals/) là tài liệu học tốt nhất ở đây — mỗi phase ghi lại quyết định thật và bug red-team bắt được (denylist→allowlist, lỗ JQL-injection, rò rỉ riêng tư qua artifact liên kết).

## Cài đặt & chạy lần đầu (5 phút)

```bash
uvx my-crew quickstart        # hoặc: pipx install my-crew && my-crew quickstart
```

`quickstart` chạy báo cáo hằng ngày của agent mặc định ở chế độ **dry-run** — chỉ cần
`OPENROUTER_API_KEY` trong `.env` (để ở `~/.my-crew/`), không ghi ra ngoài. Sau đó:

```bash
my-crew serve                 # dashboard web + coordinator, foreground
# → http://127.0.0.1:8765 — trình duyệt mở Setup Wizard (bí mật không qua terminal).
#   Node.js cần thiết cho 3 MCP server (Jira / Confluence / Slack).
```

Thích dùng container? `deploy/docker/` có Docker Compose (auth-first, state trên volume).
Operator macOS cài background service bằng `./deploy/install.sh`.
Toàn bộ setup — tích hợp, cron, trust mode: **[docs/deployment-guide.vi.md](docs/deployment-guide.vi.md)**.

## Đánh giá code

```bash
git clone git@github.com:phuc-nt/my-crew.git && cd my-crew && uv sync
uv run pytest    # 2982 BE test pass, không cần bí mật (FE: 282 vitest + 8 Playwright)
```

`DRY_RUN=true` mặc định — agent log ý định mà không đăng gì. Để chạy thật, theo **[docs/deployment-guide.vi.md](docs/deployment-guide.vi.md)**.

## Giấy phép

[Apache 2.0](LICENSE). Các mẫu kiến trúc được nghiên cứu (không sao chép) từ các harness LangGraph production; xem [docs/research/](docs/research/).
