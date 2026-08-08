# Cứng hoá tầng chấm & phán đoán — dọn backlog + 2 tối ưu + 5 lỗi sống mới
2026-08-08 · ✅ Done

## Làm gì
- Dọn sạch backlog 08-07: audit search ghi `actor` (`db6fae3`) · artifact lưu lý do self-check trượt (`51f8e4e`) · amend cho bước mới deps vào bước frozen done/running, cấm failed (`5bd3ad9`) · `DEFAULT_MODEL` theo fleet qwen + 4 test heartbeat hết đọc DB production (`dd00a53`).
- 2 tối ưu: sanitizer deep_agent 5 call → 1 call batch marker-delimited, fail-closed khi marker hỏng, chống forge marker nhảy kênh persona (`e5eb033`) · digest mirror đi coordinator-first — MY ADMIN im lặng, mọi tin về chat giao việc (`fc5f167` + `9e5ee98` hôm trước).
- Vòng 7 e2e (lãi suất 5 ngân hàng) lộ + vá 5 lỗi sống: grader không biết "hôm nay" → chấm dữ liệu 8/2026 thật là "tương lai/bịa" → neo ngày vào self-check + review (`4b6d1f0`) · decompose thổi phồng đề ("link nguồn" → "link chính thức ngân hàng") → luật TRẦN: đề gốc CEO thắng tiêu chí thổi phồng (`ed108c6`) · gate reassign chỉ nhìn cờ `web_search` → xét cả tier (deep_agent không mạng ≠ search được) (`a1bd8a1`) · retry adopt checkpoint chết giữa chừng → resume tại rework không-tool, guidance không bao giờ được đọc, lặp nguyên văn "thư xin quyền" → redo xóa thread (`512ba6d`) · researcher cạn 16 vòng tool với đề nhiều chủ thể → `runtime_loop_limit: 28` per-profile.
- Retry-first + coercion kiểm chứng sống 2 lần (log `coerced to retry_with_guidance`); tin "✅ HOÀN THÀNH" kèm link workroom về đúng chat pong, xác nhận qua dedup key per-bot.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Đề gốc CEO là trần chấm điểm | Prompt hiệu chuẩn decompose không giữ nổi qua stochastic; trọng tài ở grader là tầng chặn cuối | Grader thêm một luật, prompt dài hơn |
| Redo xóa checkpoint thread | Resume dành cho crash; retry-with-guidance cần perceive chạy lại mới đọc được guidance | Mất tiến độ giữa chừng của attempt bị kill (đúng ý nghĩa "làm lại") |
| Batch sanitizer thay vì cắt kênh | Giữ nguyên phạm vi che chắn, giảm 80% call | Marker hỏng → fail-closed network-off (hiếm, đo được) |

## Vấp & học được
- Vòng 7 kết thúc `done` nhưng "chưa thể hoàn thành do thiếu 100% dữ liệu" — trung thực tuyệt đối, không một số liệu bịa; chuỗi drop-bước của autopilot + sentinel "KHÔNG CÓ KẾT QUẢ" giữ đúng nguyên tắc xuyên 3 bước.
- Test đọc DB production là bom hẹn giờ: 4 test heartbeat đỏ đúng sáng có task stalled thật; mirror test lệ thuộc registry thật sẽ đỏ trên CI — cả hai vá bằng cách ly/fallback seam.
- "Xin phép tra cứu" có 2 nguồn khác nhau: memory poisoning (đã vá 08-07) VÀ rework-node không tool bị resume lặp (vá hôm nay) — cùng triệu chứng, khác bệnh; đọc kỹ artifact mới phân biệt được.

## Chiều 08-08 — capstone
- **Vòng 8 (lãi suất, đề nhắn lại): PASS SẠCH TUYỆT ĐỐI** — 5/5 bước lần 1, 0 can thiệp, $0.05 (vòng 7 cùng đề: $0.11, chết bước đầu sau 6 attempt). Số thật kèm nguồn + thời điểm (VPBank 6,4/6,6%, VCB 4,7% CafeF 12/2025), 3 ngân hàng khai THIẾU trung thực. Toàn bộ 2 ngày fix được kiểm chứng trong một vòng.
- Nút "Huỷ việc này" hoá ra chỉ ghi nhận (v1 by-design "does NOT auto-act") — CEO bấm mà task đứng im; vá: follow-up sweep tiêu thụ câu trả lời rung-2, huỷ thật + mốc ❌, hành động đúng 1 lần qua `resume_token` (`8e2a5c5`); câu bấm cũ được tiêu thụ hồi tố.
- Tin ✅ vẫn đúp sau fix sáng: tường lửa PII (`office_event_projection` whitelist) nuốt lặng lẽ cờ `delivered_direct` lúc GHI — người viết đặt cờ, firewall ăn cờ, mirror không bao giờ thấy. Vá whitelist cho cờ routing đi qua (`9794c32`). Bài học: cờ mới đi qua tầng chiếu phải kiểm cả BÊN ĐỌC lẫn BÊN GHI.

## Mở / sang sau
- Đặt `MPM_WEB_BASE_URL` (Tailscale/LAN) để link 🔎 bấm được từ điện thoại — chờ CEO cho địa chỉ.
- Cân nhắc: khi loop cạn quỹ, thay degrade-về-rỗng bằng một call chốt "tổng hợp từ những gì đã tra được".
- Autopilot dead-step reset giữ nguyên assignee cũ (kể cả người thiếu năng lực) — gate tier mới chặn đường vào, nhưng reset chưa biết chọn lại người.
