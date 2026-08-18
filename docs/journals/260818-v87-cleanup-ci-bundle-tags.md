# v87 — Vòng dọn dẹp sau release: CI actions, deprecation, bundle, tags
2026-08-18 · ✅ Done (4/4 phase, plan `plans/260818-2002-cleanup-ci-deps-bundle/`)

## Làm gì
- **CI thoát Node 20**: bump 6 action trong 3 workflow (checkout v4→v7, setup-node v4→v7, upload-artifact v4→v7, download-artifact v4→v8, setup-uv v5→v10.0.1, action-gh-release v2→v3). Đọc breaking notes từng cặp major trước khi bump; CI xanh 5/5 job, annotation deprecation biến mất.
- **Hết warning cuối của suite**: thêm `httpx2` vào dependency-group dev — TestClient của Starlette bỏ backend httpx cũ. httpx2 là package riêng nên httpx mà openai SDK dùng không bị đụng.
- **Entry bundle -38%**: `chart.js` (493K nguồn) rời entry qua `lazy-charts.tsx` — chỉ Cost + Guardrail tải. index 777→504 kB (gzip 240→149). Chunk lỗi degrade thành một dòng thông báo, số liệu quanh nó vẫn nguyên.
- **Tag sạch**: xóa `v39`/`v49`/`v50` (đặt theo số arc trước khi chuyển semver) + Release đính kèm v39; `git tag` chỉ còn v0.1.0..v0.11.0.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Không split `agent-desk` (900 kB), nâng `chunkSizeWarningLimit` lên 950 | Sourcemap cho thấy 94% là `three` + r3f của đúng một view đã lazy sau /office — chia nhỏ chỉ phân mảnh dependency của chính view đó | Limit cao hơn; đặt sát trần hiện tại để warning vẫn bắt thứ MỚI phình |
| Pin `setup-uv@v10.0.1` full version thay vì major tag | Từ v8 action này ngừng publish tag major/minor để chống supply-chain — `@v10` không tồn tại | Phải bump tay; đã ghi comment tại chỗ pin |
| Đo bundle bằng sourcemap thay vì thêm visualizer | `sourcesContent` trong .map đủ để quy khối lượng về từng package | Không có UI treemap, đọc bằng script một lần |

## Vấp & học được
- Định bump theo trí nhớ thì hỏng: khoảng cách thật xa hơn dự đoán (download-artifact đã ở v8, setup-uv v10) và setup-uv đổi hẳn chính sách tag. Tra `releases/latest` + `matching-refs/tags` trước khi viết version vào workflow.
- Grep chuỗi trên bundle minified để đoán "thư viện nào nằm chunk nào" cho kết quả vô nghĩa (`three: 2` trong chunk 900 kB toàn three). Sourcemap là nguồn số đo, grep thì không.
- Test mock cũ (`vi.mock('../components/charts/CostChart')`) vẫn xanh sau khi view chuyển sang lazy wrapper — vì wrapper import đúng module đã bị mock. Lazy hoá tại điểm dùng, giữ nguyên module gốc, thì test không phải sửa.

## Mở / sang sau
- Đường publish thật (action-gh-release v3, download-artifact v8) mới verify qua release notes; xác nhận ở lần cắt tag kế.
- `three` cảnh báo `THREE.Clock` / `PCFSoftShadowMap` deprecated trong log e2e — nợ riêng của view 3D.

Suite: 3526 BE (0 warning) + 303 FE + 10 e2e, tsc/ruff sạch.
