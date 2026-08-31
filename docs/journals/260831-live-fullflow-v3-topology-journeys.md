# Live fullflow v3 — topology thật, journey xuyên tính năng, benchmark 7 trục
2026-08-31 · ✅ Done

## Làm gì

- **Nâng trục "thật"**: từ (LLM thật, runtime in-process) lên (LLM thật + tiến trình
  `my-crew serve` thật + HTTP thật + coordinator tick thật). Harness spawn server thật,
  nói chuyện qua socket, không gọi thẳng route handler nữa. Knob `MY_CREW_TICK_INTERVAL_S`
  để tick nhanh trong test mà không phải tiêm code test vào sản phẩm.
- **54 case** thay 33: thêm journey xuyên tính năng (J1–J5, gồm kill -9 giữa task rồi boot
  lại), adversarial injection thật trong nội dung việc (X1–X4, mỗi đòn kèm case đối chứng
  dương b/c để assert không xanh rỗng), và topology smoke.
- **Benchmark v3**: thêm 2 mode `reliability` (tỷ lệ router quyết giống nhau qua k lượt) và
  `journey` (hình dạng công việc: số chặng, số lần chạm người, chết ở đâu). Baseline 0.15.0
  commit ở `bench/` — KHÔNG để trong `my_crew/` vì `pyproject.toml` khai
  `packages = ["my_crew"]`, để đó là ship artifact nội bộ tới mọi người cài gói.
- **Chạy 2 lượt live**: lượt 1 **53/1** (28:49), lượt 2 **54/54** (27:56) sau khi vá.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Gate live bằng `pytest_collection_modifyitems`, không `pytestmark` | pytest **im lặng bỏ qua** `pytestmark` đặt trong conftest — gate tưởng có mà không có | Phải nhớ quy ước; bù lại file mới trong `tests/fullflow_live/` tự động được gate |
| Trần chi phí per-case cứng trong fixture teardown | Suite thật đốt tiền thật; trần từng case chặn sớm hơn trần cả suite | Không có tổng suite khi chạy `-q` (stdout case xanh bị nuốt) |
| `journey` compare-only, không có nửa "run" | Baseline do live suite cắt — nó đã sở hữu fixture, fleet boot, trần ngân sách. Thêm đường cắt thứ hai trong script là đường yếu hơn tới cùng một JSON | Muốn baseline mới phải chạy suite, không chạy script |
| Mọi comparator phải chứng minh ĐỎ được, không chỉ xanh | Tự-so-chính-nó luôn in "no differences" — mode hỏng vẫn trông chạy được cho tới đúng lần đầu có việc thật | Tốn thêm một vòng tiêm đột biến mỗi comparator |

## Vấp & học được

- **Đếm đúng ≠ phân tích đúng.** B0 (cụm ngoặc viết thường nuốt chủ thể) sửa xong, test A8
  xanh, số thực thể đúng 12. Nhưng in giá trị thật ra xem thì thực thể thứ 12 là
  `'Nhà Thuốc Long Châu (hạng mục'` — lớp ký tự `[^.\n:?!]+` không dừng ở `(`. Định tuyến
  không đổi nên **mọi assert theo số lượng đều xanh**; thiệt hại nằm ở hai consumer dùng
  CHUỖI: `_split_entities` ghi tên vào title + acceptance của bước, và sprint tìm kiếm
  nguyên văn. Nghĩa là một nhân sự bị giao đi nghiên cứu công ty có mẩu rác dính vào tên.
  Chỉ lộ khi in ra xem thay vì tin test xanh.
- **Tôi suýt lặp lại đúng lỗi đang đi sửa.** Đang vá tài liệu benchmark (epilog ghi "Five
  modes" trong khi có 7, `releasing.md` nói `journey` ghi JSON qua `--out` trong khi nó
  compare-only — và tự mâu thuẫn với chính nó 100 dòng bên dưới), bản vá đầu của tôi **bịa ra**
  `journey --out cand-journey.json`. Bắt được vì chạy `--help` thật thay vì đọc lướt. Giờ mọi
  dòng lệnh trong epilog được parse-check đối chiếu argparse thật (10/10).
- **Dựng lại hiện trường bằng trí nhớ là sai.** A8 đỏ vì assistant viết lại đề bài; tôi đoán
  bản viết lại → ra 0 thực thể, không phải 8. Phải moi đề THẬT từ sqlite của lượt chạy mới
  root-cause đúng (và phát hiện cột tên `original_request` chứ không phải `brief`).
- **Im lặng không phải là xanh.** `-q` buffer toàn bộ tới lúc thoát, nên monitor tail log
  không thấy gì suốt 28 phút — dù pass hay crash đều im như nhau. Phải theo dõi tiến trình
  còn sống + fleet con, rồi bắn sự kiện lúc THOÁT.

## Mở / sang sau

- **B1 + B7 đã sửa sau khi CEO duyệt** — xem `260831-b1-b7-fix-va-gmail-root-cause.md`.
- A8 đã lên 2/2: chạy bù riêng nhóm routing (8/8, 14:50) trên mã vá cả B0 lẫn B6, rẻ hơn một
  lượt 54-case 28 phút. 46 case ngoài nhóm routing vẫn dừng ở 2 lượt đầy đủ.
- Tiền tố truy vấn vẫn hút chữ từ mệnh đề ngoặc (`'sàn hạng mục thị trường chính Shopee'`).
  Có sẵn từ trước, không do B6, ở ca này vẫn tìm đúng — ghi lại, chưa sửa.
