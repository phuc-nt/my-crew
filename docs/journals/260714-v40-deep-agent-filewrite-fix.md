# v40 — deep_agent sandbox file-write fix
2026-07-14 · ✅ Done (2226 BE)

Từ benchmark 3-harness (MPM/OpenClaw/Hermes §10.3): deep_agent crash 3/4 lần khi ghi file. Vá 1 bug production thật.

## Làm gì
- **Bug**: `upload_files`/`download_files` của cả DockerSandboxBackend + FakeSandboxBackend là STUB trả `[]`. deepagents filesystem-middleware gọi `write_file` → `upload_files` kỳ vọng 1 response/file, nhận 0 → assert crash. Agent qwen3.7 luôn muốn ghi report ra file → 3/4 run benchmark chết.
- **Fix**: implement 2 method thật — trả đúng 1 `FileUploadResponse`/`FileDownloadResponse` mỗi file. File confine trong `/work`. deep_agent vẫn trả kết quả cuối qua text-reply (record_loop_result — không đổi deliver).
- 19 test (unit + real-Docker gated E2E round-trip binary bytes + path-confine).

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Docker I/O qua **exec+base64**, KHÔNG put_archive/get_archive | `/work` là tmpfs mount trên rootfs **read-only** (moat harden) → put_archive báo "rootfs read-only", get_archive không đọc tmpfs. exec ghi/đọc landing đúng tmpfs | Không dùng Docker archive API (đã bỏ tar helper) |
| deep_agent trả kết quả text-reply (không file-download-trước-teardown) | CEO chốt; đường deliver sẵn, khớp d1 benchmark chạy được; file trong sandbox là scratch cho agent tự đọc/ghi khi làm | File cuối không lấy ra ngoài (nhưng report vào text-reply đủ) |
| nghien-cuu GIỮ deep_agent | CEO chốt — sau vá, chất lượng sâu (§10.2) không còn kẹt crash | Chậm 5× tool_calling (chấp nhận cho độ sâu) |

## Vấp & học được
- **Real Docker E2E bắt bug thiết kế**: kế hoạch định dùng `put_archive` (tar) nhưng container rootfs read-only → fail ngay lần chạy Docker thật. Unit test (Fake) không bắt được. → đổi exec+base64. **Live Docker > fake test** một lần nữa.
- **Self-review bắt shell-injection**: path interpolate vào `sh -c` cmd → path `a; rm -rf /work` sẽ chạy. `_confined_rel` trước chỉ chặn `..`, không chặn metachar. → thêm `_SAFE_PATH_RE` (chỉ `[A-Za-z0-9._-/]`). Verify real Docker: `a; touch /work/HACKED` refused, file KHÔNG tạo. **Path-confine phải chặn cả traversal LẪN shell-metachar khi path vào shell.**
- Bug này là giá trị THẬT của benchmark (đã tự rút "MPM tốt nhất" over-claim) — 1 finding actionable tiền-đề-chín.

## Mở / sang sau
- deep_agent lấy file BINARY ra ngoài (nếu task cần artifact) — hiện text-reply only.
- #D full-fleet parallel benchmark, #E PM-task benchmark — chưa cần (đo, không phải bug).
