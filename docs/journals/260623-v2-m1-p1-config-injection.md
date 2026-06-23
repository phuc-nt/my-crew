# v2 M1-P1 — Config-injection (giết 2 config singleton)

2026-06-23 · ✅ Done (4 slice A→B→C→D, commit 031a543 / 8bafe54 / 8aba547 / e1a39b8)

## Làm gì

- Xóa 2 `@lru_cache` singleton `get_settings()` + `get_reporting_config()`. Grep `src/` còn **0 hit**.
- Thay bằng builder ở `src/config/config_builders.py`: `build_*_from_dict(d)` (thuần, dict→dataclass, giữ validate stakeholder-channel) + `build_*_from_env()` (load_dotenv→os.environ→dict→from_dict, byte-identical v1).
- Thread `config: ReportingConfig` + `settings: Settings` làm tham số tường minh qua toàn bộ call graph: store (audit/dedup/approval nhận path), BudgetTracker/LlmClient/ActionGateway nhận Settings, 3 graph factory + tool fetcher + section helper nhận config+settings, entrypoint build 1 lần rồi inject xuống.
- Handler Slack/Confluence dựng qua closure factory (`make_slack_post_handler`/`make_create_page_handler`) → server spec mang token KHÔNG vào audit log / approval queue.
- 282 test xanh, ruff sạch ở mọi slice. Guardrail chain (Lớp A/B, audit, budget, dedup) không đổi — P1 chỉ là plumbing.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| `from_dict` core + `from_env` wrapper | from_dict thuần để P2 nạp `profile.yaml → dict → from_dict` (per-agent); from_env giữ v1 byte-identical làm mốc back-compat | 2 hàm thay 1, nhưng tách I/O khỏi validate |
| Handler = closure bind config, KHÔNG nhét spec vào action dict | audit log `json.dumps` không có `default=str` + redact bỏ qua dataclass → spec sẽ vỡ serialize VÀ rò token vào audit/approval | bỏ phương án "embed spec vào action" đã định ban đầu |
| `external_channels` inject, default `frozenset()` | mọi construction thật truyền set từ config → guardrail Lớp B fail-closed; xóa `_load_external_channels` đọc singleton | gateway rỗng set thì không phân loại external nào (an toàn) |
| `build_*_graph` raise ValueError khi `deps=None` mà thiếu config/settings | fail-closed: không cho path thật âm thầm rớt về default rỗng | BREAKING — entrypoint + test phải truyền |
| `audit`/`hello` build config LAZY (không build ở đầu `main()`) | review bắt: build vô điều kiện làm `audit` chết khi reporting config sai → lệnh chẩn đoán phải sống qua misconfig | thêm vài dòng dispatch |

## Vấp & học được

- **Slice chồng nhau:** B làm constructor strict → graph/cli/cron gọi bare bị vỡ ngay, không chờ tới C/D. Phải bắc cầu `build_settings_from_env()` tạm trong graph (B), rồi mới nâng thành tham số (C) và xóa singleton (D). Slice-per-commit giữ suite xanh ở từng mốc.
- **Rename `cfg`→`config` sót 2 chỗ** ở delivery path daily/weekly → `NameError`, test giả-writer che mất, **ruff bắt** (F821). Bài học: ruff là lưới chót cho rename khi test mock writer.
- **`from_dict` rò `get_reporting_config()` chỉ trong docstring** vẫn làm grep-gate đỏ → phải sửa cả văn docstring, không chỉ code.
- Review tìm 2 finding non-blocking (audit eager-build + test `*_no_key` không clear SLACK env) → vá luôn trong slice, không hoãn.

## Mở / sang sau

- File >200 LOC tồn từ trước (hard_block 436, action_gateway 331, report_graph 259, cli 241) — P1 không đẻ ra, modularize hoãn.
- P2: profile loader `profile.yaml → dict → from_dict`; `bindings.*.token_env` resolve tên env→giá trị lúc spawn (P1 đọc token thẳng từ env như v1).
- P3: `data_dir` đã là field inject được → per-agent `.data/agents/<id>/`.
- Đề xuất P4/test: 1 test E2E assert `gw._external_channels == config.slack_external_channels` để khóa invariant guardrail (giờ chỉ verify bằng đọc code, vì test deps inject `gateway=` sẵn).
