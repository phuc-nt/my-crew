# v74 — Tối ưu tốc độ task đa-agent (tier theo bước + dispatch sự kiện + fan-out)
2026-08-08 · ✅ Done

## Làm gì
- **Tier theo bước** (`needs_web`): decompose gán flag per-step; bước work không cần
  web + review row → ép native one-shot (`resolve_step_runtime`); rework giữ tier
  agent; hint sai tự hồi phục sau ruling đầu. Bind plan-hash có điều kiện (tiền lệ
  `needs_shell` — DAG cũ hash y nguyên).
- **Dispatch hướng sự kiện** (`tick_poke.py`): worker team-step thoát → touch
  `.data/tick.poke`; service ngủ lát 5s, mtime vượt watermark → spawn 1 team-tick sớm
  (debounce, stale-safe). Nhịp 60s giữ làm fallback.
- **Fan-out đa thực thể**: prompt decompose thêm quy tắc ≥4 thực thể độc lập cùng
  dạng → 2-3 bước collect song song, tên thực thể đích danh trong title + acceptance.
- E2e đo (đề 5 trợ lý AI, task 0a03ebc1ab2f): wall 25,8' vs 40' vòng 8, $0.083,
  delivered; 2 collect song song thật; gap dispatch bước sẵn-deps 1–17s (trước: 253s
  tổng/task).

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Ép native theo flag bước, không đổi tier agent | 64% wall-clock đo được là bước không-tool trên tier nặng (qa 548s deep, finalize 780s loop) | Hint sai làm bước thiếu tool → chấp nhận, tự hồi phục sau 1 ruling |
| Poke file mtime, không IPC/queue | KISS: touch + stat là đủ, cả 2 đầu best-effort | Độ trễ trần 5s (lát ngủ), đủ tốt |
| Fan-out là hint prompt, không ép validator | Stochastic nhưng validator đã hỗ trợ shape; ép code là YAGNI | ~2/3 lần decompose chịu tách; re-roll khi cần |

## Vấp & học được
- Flag mới PHẢI nằm trong **schema ví dụ** của prompt decompose — chỉ định nghĩa bằng
  văn xuôi thì model mirror ví dụ và không emit (`needs_web=0` toàn bộ vòng e2e đầu,
  suýt chạy research trên tier không có search). Vá + pin test (112033f).
- Gap "lớn" còn lại trong đo e2e không phải dispatch: retry research_1 (+~7') và 2
  vòng review-rework finalize (+~8') là vòng chất lượng hoạt động đúng; sub-step cùng
  agent chạy tuần tự (single-flight per agent) là trần song song thật.
- `cd` sang plan dir làm lệnh `.venv/bin/python` sau đó fail — dùng đường dẫn tuyệt
  đối trong session dài.

## Mở / sang sau
- Rework row spawn còn chờ ~65s (ruling tạo row xong đợi tick kế) — có thể poke ngay
  sau ruling nếu muốn ép tiếp.
- Theo dõi tỷ lệ decompose chịu fan-out; <50% đề đủ điều kiện thì cân nhắc ép code.
