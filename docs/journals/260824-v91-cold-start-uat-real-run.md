# v91 P6 — cold-start UAT chạy thật: 4 bug chỉ lộ khi cài mới
2026-08-24 · ✅ Hoàn thành · plan `260819-2041-ux-real-use-journeys` đóng

## Làm gì

- **Chạy trọn 8 bước UAT trên máy-trắng thật**: venv mới + `pip install .` + `MY_CREW_HOME`
  rỗng + port 8799 (tách khỏi fleet 8765), browser chromium thật, OpenRouter key thật,
  bot Telegram thật. Kết quả từng bước ghi ở `reports/uat-cold-start-real-run.md`.
- **Đóng băng hành trình thành harness** `web/e2e-uat/` (7 spec + `uat-login.ts` +
  `playwright.uat.config.ts`) — bước 8 là lệnh CLI nên không có spec.
- **4 bug tìm được, sửa và test hết**: wizard đá nhầm dịch vụ instance khác (`b79a101`),
  bind Telegram không ghi `ops_operator_id` khiến guard không bao giờ thoả (`6cdee39`),
  `mcp` không ghim resolve lên 2.0.0 giết mọi tích hợp MCP từ lúc cài (`020385b`),
  khối comment mẫu bị nhận nhầm làm con của `schedule` sau khi form điền (`0af1b84`).
- **Docs**: hai bước ẩn của hành trình (agent tạo ra đang tắt; tuyển ≠ đặt
  `coordinator_id`), invariant thứ tự comment trong profile mẫu, và dòng troubleshooting
  cho lỗi import `mcp`.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Test bằng text đã render, không bằng giá trị đã parse | Bug ruamel không đổi giá trị — parse luôn đúng; assert ở mức value mù hoàn toàn với nó | Test bám vào layout file, dễ vỡ khi format đổi — chấp nhận vì đó chính là thứ cần khoá |
| Sửa template (đảo thứ tự comment) thay vì sửa `profile_patch` | Thử 3 hướng code-level (rebind, mutate tại chỗ, chèn dòng trắng) đều ra output y hệt: đây là mô hình comment của ruamel, không phải lỗi ta | Ràng buộc cách viết file mẫu → phải có test canh, đã thêm |
| Nút "Thử lại bước" thay vì "Chấp nhận kết quả" ở bước 5 | `accept_step` chỉ đúng khi task kẹt vì review; board cố ý không phân loại kiểu kẹt, backend 409 kèm lý do | Không phải bug — nhưng spec phải chọn nút áp dụng cho MỌI kiểu kẹt |
| `e2e-*` khớp theo tiền tố trong vitest exclude | Danh sách liệt kê tên đã vỡ 3 lần liên tiếp, mỗi lần thêm 1 thư mục e2e mới | Không có |

## Vấp & học được

- **Ba trong bốn bug cùng một hình dạng**: app chỉ đúng việc phải làm, nhưng làm theo
  thì không sửa được vấn đề. Lỗi `mcp` bày hướng dẫn "đặt token" cạnh một ImportError;
  guard Telegram đòi trường mà chính luồng bind không bao giờ ghi. Đây là lớp lỗi
  fixture không bắt được: mọi unit test đều dựng sẵn trạng thái đúng.
- **`e2e-uat` không nằm trong tsconfig nào** nên chưa từng được typecheck — đó là lý do
  một `string | undefined` lọt qua và một tên biến môi trường cũ (`HR_...` thay vì
  `COORDINATOR_...`) chỉ pass nhờ shell lúc đó tình cờ có export. Thêm vào
  `tsconfig.e2e.json` rồi mới commit.
- **Commit harness làm vỡ vitest**: `e2e-uat` bị collect vì exclude liệt kê theo tên.
  Cùng lúc lộ chuyện toggle advisor mượn class `.agent-dry-run-toggle` — class không có
  CSS, thuần test hook — làm 2 spec trust-mode nhập nhằng.

## Mở / sang sau

- Bước 2 (wizard) không chạy lại được trên home đã cấu hình; muốn gate CI thì cần
  seed lại home rỗng mỗi lần.
- `@coordinator` không giao việc được là đúng thiết kế, nhưng tên "Trưởng phòng
  (Điều phối đội)" trong danh sách tuyển vẫn dễ gây hiểu nhầm.
