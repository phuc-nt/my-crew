# Vòng cứng hoá tự chủ — e2e 2 vòng, 7 fix
2026-08-07 · ✅ Done

## Làm gì
- Vá `team-tick` vào `_CAP_EXEMPT_KINDS` (`service.py`): coordinator hết bị bỏ đói sau 5 inbox poller — phán quyết từ >3h xuống ~1 phút (`16bfa54`).
- Đổi toàn fleet 12 profile sang `qwen/qwen3.7-plus`; vá aggregate prompt chống CoT-leak (qwen viết "thinking process" tiếng Anh vào summary → Telegram cắt 4096 chỉ còn phần leak) (`fa3c7d1`).
- Bộ lọc memory `_parse_facts`: chỉ nhận câu khai báo 1 dòng, chặn header/bảng/câu hỏi/lời tự phủ nhận "không có khả năng", cap 5 fact/lần; dọn tay MEMORY.md researcher đã nhiễm (`69eb825`).
- Deep_agent: sandbox network-off bỏ qua LLM sanitizer (không có đường rò để chống mà nó gọt sạch URL + nén handoff); network-on giữ sanitize, prompt giữ nguyên URL công khai (`89a9175`).
- Self-check phải kiểm THẬT tiêu chí đếm được (đòi link mà 0 chuỗi `http` = trượt) + decompose bắt bước chốt fan-in deps thẳng vào mọi bước tạo dữ liệu (`6144f4a`).
- E2e 2 vòng qua đúng đường preview→confirm: vòng 1 `stalled` (give_up trung thực sau 2 can thiệp — chính nó lộ 4 lỗi trên); vòng 2 done 5/5 step, báo cáo 9 URL, aggregate sạch, mirror push Telegram xác nhận qua dedup key.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| team-tick miễn tick-cap | 1 coordinator duy nhất → +1 worker/tick, còn starvation là deterministic | Cap bớt "đều" đi một suất |
| Network-off ⇒ bỏ sanitize | Sanitizer chỉ chống egress; không mạng thì chỉ còn tác hại (mất URL/chi tiết) | Network-on vẫn tốn 5 call sanitize |
| Lọc fact bằng code, không prompt | Prompt đã cấm mà vẫn lọt (đo được); filter deterministic test được | Regex denial có thể chặn nhầm biên |
| Bước chốt fan-in deps trực tiếp | Dữ liệu không tự truyền qua tầng; finalize deps=[qa] mù URL của research vĩnh viễn | Handoff bước chốt dài hơn |

## Vấp & học được
- Memory tự đầu độc là vòng kín: 1 lần refusal (thời native không tool) → ghi vào MEMORY.md → mọi run sau đọc "tôi không tra web được" cạnh capability "web_search: bật" → refusal tiếp. Phá vòng phải bằng filter ở đường GHI, không chỉ dọn file.
- Give_up của vòng 1 không phải thất bại của hệ — nó trung thực đúng thiết kế và là công cụ lộ lỗi tốt nhất phiên này.
- Model đổi (minimax→qwen) đổi cả dạng lỗi: CoT-leak vào content là lỗi mới, không có ở model cũ — swap model cần soát lại các call lấy `content` thô.

## Mở / sang sau
- ~~Coordinator chuộng `reassign` ngay lần trượt đầu~~ → đã vá 08-07/08-08: retry-first (`6c34353` + `1d10b8a`), reassign chỉ từ ruling 2.
- ~~Audit `web_search` không ghi `actor`~~ → đã vá 08-08 (`db6fae3`): actor = basename data_dir per-agent, cả 3 call site.
- Đã vá thêm 08-08: artifact lưu lý do self-check trượt (`51f8e4e`); amend cho new step deps vào bước frozen done/running, cấm failed (`5bd3ad9`); `DEFAULT_MODEL` theo fleet qwen + test heartbeat cách ly team-task store — 4 test đọc nhầm DB production, đỏ đúng sáng có task stalled thật (`dd00a53`). Suite 2.923 pass.
- Còn lại: deep_agent network-on sanitize 5 call/step khá đắt, cân nhắc chỉ sanitize handoff + memory; mirror admin có thể thu về fallback-only nếu CEO muốn.
