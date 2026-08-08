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

## Vòng dọn tồn đọng (cùng ngày, tối)
- **Poke sau action** (`poke_worthy`): tick kết thúc bằng spawned/aggregated/
  stuck_retry/stuck_reassigned → poke tick kế (~5s thay vì 65s giữa ruling và spawn
  rework); "none" và dead-end không poke nên chuỗi luôn tự dừng.
- **Salvage transcript khi cạn loop** (`invoke_capped` → stream + 1 lượt tổng hợp
  bounded): loop 28 vòng đã fetch dữ liệu thật không còn trả kết quả rỗng — tổng hợp
  từ phần đã có, thiếu ghi THIẾU, hỏng nữa mới degrade rỗng như cũ.
- **Dead-step reset đổi người**: bước `needs_web` chết mà assignee không search được →
  reset chuyển cho đồng nghiệp web-capable đầu tiên (registry order); không ai đủ →
  giữ nguyên. `_can_do_step` giờ dùng thẳng cờ `needs_web` (docstring cũ "không có cờ
  needs-web" đã hết đúng từ v74).

## Benchmark (cùng ngày, khuya — báo cáo đầy đủ ở plans/reports/benchmark-260808-2234)
- 2 vòng e2e thêm: bench-1 (5 cloud storage) **11,0' / $0.0235 / 0 can thiệp**, review
  pass lần đầu, gap dispatch 0–3s; bench-2 (5 dịch vụ nhạc, không fan-out) 24,8' trong
  đó 7,5' chờ CEO trả lời clarify — máy ≈17', gap dispatch đầu **5s**.
- Bench-1 lộ 2 gap chót → vá luôn (e3eeedf): poke khi mint row (`review_inserted`/
  `fanout_inserted` — trước chờ 44–190s) + poke ngay khi confirm giao việc (trước 30s).
- Chốt số: cùng dạng đề 40' (vòng 8) → 11' khi fan-out ăn (3,6×), → ~17' máy khi
  không (2,4×); cost giảm 2–3×. Biến động còn lại = decompose có tách không (~60%)
  + vòng chất lượng (hành vi đúng).

## Bench-3 (09/08 khuya): 2 task đồng thời — lộ + vá bug split-sub
- VPN (không fan-out) **12,3' / $0.0232 / 0 can thiệp** dù chia researcher với task
  kia — tổng gap dispatch 16s; fairness + poke chain giữ nguyên hiệu quả dưới tải.
- TMĐT lộ bug thật: **split-sub mint không thừa kế `needs_web`** → 3 sub ép native
  searchless, mỗi sub đốt 1 ruling tự hồi phục, dữ liệu mỏng → gather trượt 2 lần →
  gave_up trung thực → stalled. Vá fbaedd4: sub thừa kế cờ cha qua keyword-only
  (đúng pattern guard-rail của needs_review), gather giữ False.
- Học: guard-rail "row ticker-mint là việc text-only" viết cho review/rework/gather
  không còn đúng khi split-sub mang chính việc collect của cha — flag mới phải rà
  MỌI đường mint row, không chỉ decompose.

## Mở / sang sau
- `MPM_WEB_BASE_URL` (link bấm được trên điện thoại): chốt phương án `tailscale serve`
  (giữ bind localhost, không cần password web-auth) nhưng BLOCKED — cần bật HTTPS
  certificates trong Tailscale admin console + bật lại app Tailscale trên iPhone
  (offline 44 ngày). Lệnh sau khi bật: `tailscale serve --bg 8765`.
- Theo dõi tỷ lệ decompose chịu fan-out (hiện 3/5); <50% thì cân nhắc ép code.
- Clarify answer→resume còn ≤60s (có thể poke tại `apply_answer` — YAGNI vì phần chờ
  chính là người); salvage-transcript mới có unit test, chưa bắn live.
