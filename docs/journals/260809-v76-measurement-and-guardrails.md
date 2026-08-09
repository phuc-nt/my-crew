# v76 — Đo lường bài bản + guardrail lớp mới (học từ my-dandori, giữ autonomy)
2026-08-09 · ✅ Done

## Làm gì
- **Audit hash-chain**: mỗi dòng audit mang `prev_hash`/`entry_hash` (canonical
  length-prefix — join '|' có collision, có test dựng); `mpm agent audit <id> verify
  [--team]` báo đứt tại đâu, lý do gì; nhiều worker ghi chung trail dưới flock; lỗi
  bookkeeping = restart nhìn thấy được, không bao giờ rơi dòng audit.
- **Fail-mode contract + break-glass**: `gateway_fail_contract` khai báo từng
  checkpoint fail kiểu gì khi KHÔNG eval được (closed trước side-effect; open chỉ cho
  notify/bridge), test pin từng nhánh; `MYCREW_GATEWAY_FAIL_OPEN=1` (env-only) nới
  đúng nhánh store-hỏng của Lớp B — không bao giờ nới Lớp A/kill-switch/dedup (test).
- **Metrics đội honest-data** (`agent_metrics` + lệnh chat `team_metrics`): tỉ lệ
  done/needs_decision per-agent kèm Wilson CI + n, mẫu <5 gắn `*`, bucket toàn-pass
  nói "chưa có ca hỏng để so", store hỏng degrade mềm; capture stamp `profile_hash`
  (provenance: attempt chạy với bản prompt/policy nào).
- **Autonomy band + closed loop bất đối xứng**: supervised/normal/trusted per-agent,
  CHỈ đổi cổng peer-review (bất biến thành test nguồn: `band_for` không được xuất
  hiện trong dispatch/routing/gateway/cost/ladder); loop giờ-một-lần: xấu rõ (≥p90,
  CI tách median, n≥5, fleet≥3) tự siết; mơ hồ chỉ ĐỀ XUẤT; hồi phục tự gỡ; trusted
  chỉ qua tay CEO (`set_band`); cooldown 3 ngày; mọi thay đổi audit kèm công thức +
  báo Telegram.

## Kiểm chứng sống (cùng ngày)
- Chain: trail thật 829 dòng legacy verify OK; 3 dòng mới tự mang hash, verify OK.
- Loop **tự bắn qua tick thật ngay sau commit**: demote `researcher` (nd 46%, CI
  37–56%, n=106 vs fleet p90 46%) + đề xuất cho `analyst` — audit row có chain hash,
  Telegram mirror. Ba phase hội tụ trong một dòng bằng chứng.
- Suite 3013 BE, ruff sạch; hành vi task thường byte-identical khi mọi band ở normal.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Band chỉ đụng cổng review | CEO yêu cầu giữ autonomy + phối hợp nguyên vẹn; siết đúng chỗ rẻ nhất (double-check) | Không chặn được agent yếu nhận việc khó — để vòng sau nếu cần |
| Siết tự động / nới cần người (trừ hồi phục về normal) | Bất đối xứng my-dandori: sai theo hướng an toàn | Demote nhầm khi metrics lệch — có CI + min-sample + cooldown đỡ |
| Đọc band không tạo file store | Test isolation + fleet chưa dùng band = 0 side effect | — |
| Truncation-tail chưa bắt được (chưa ký + checkpoint ngoài) | Máy đơn: key sống cùng chỗ, checkpoint local chỉ là automation | Ghi rõ giới hạn trong docstring, làm khi có máy thứ hai |

## Vấp & học được
- Loop wired vào tick chạy NGAY ở tick kế (worker import code mới) — live e2e "tự
  đến" trước khi kịp chạy tay; may mà mọi nhánh đều audit + notify nên quan sát đủ.
- `settings_factory` fixture sẵn có làm contract test gateway rẻ hơn dự kiến nhiều.

## UAT toàn stack (chiều 09/08 — 5 task sống, 7 pattern, ~$0.27)
Báo cáo đầy đủ: `plans/reports/uat-260809-1620-full-stack-v74-v76-live-patterns-report.md`.
- Đủ 7 pattern PASS, trong đó 3 ca sống đắt giá: goal-replan **áp thành công tự
  nhiên** (T1: thay qa+finalize bằng 2 bước mới → done với data thật) VÀ **từ chối
  fail-closed** (T3 doomed: amend 3 lần deps sai → validator chặn, stalled chờ CEO);
  supervised ép soát cả bước thu thập; trusted waive terminal nội bộ (sau fix).
- 3 bug thật tìm + fix + verify trong phiên: decompose cạn retry vì model noise
  (60d4650); amend không nêu rõ deps hợp lệ (c798a20); **trusted band no-op** —
  policy v64 chỉ flag terminal+external mà rule trusted giữ nguyên cả hai → rỗng
  giao (77be73b). Bài học: rule mới phải đối chiếu PHÂN BỐ THẬT của cờ nó điều
  chỉnh, không chỉ đúng về logic.
- Audit chain sống sót bão đa-worker: 897 dòng, 68 hashed mới, 0 restart, verify OK.

## Mở / sang sau
- Ed25519 ký + checkpoint ngoài data-dir (bước 2 của chain) — khi có nhu cầu multi-machine.
- Band hiện chưa hiện trên kanban card (mới có audit/Telegram/`team_metrics`).
- Theo dõi demote researcher: nếu supervised giúp done-rate hồi phục, loop sẽ tự gỡ.
