# v11 P4 — esbuild bundle + npm publish + installer npm-path (2026-07-08) · v11 HOÀN TẤT

Tier 3 (distribution). 3 server repo + my-pm. Kết thúc v11.

## Đã làm

- **esbuild single-file bundle** cả 3 server (`esbuild --bundle --platform=node --format=esm` + shebang banner): `dist/index.js` self-contained → spawn không resolve node_modules, npm-install chỉ cần 1 file. `tsc --noEmit` giữ làm typecheck riêng. `files` chỉ ship dist + README. Cả 3 bundle SẠCH (kể cả winston/slack — không dính ESM issue). Commit từng repo (`955d303` jira, `6fa3223` confluence, `2ecc3d1` slack).
- **Publish npm** (chủ dự án chạy vì cần OTP 2FA): `mcp-jira-cloud-server@4.2.0`, `confluence-cloud-mcp-server@1.5.0`, `slack-browser-mcp-server@1.3.0`. Verify `npm view` = đúng target.
- **install.sh npm-path** (mặc định): `npm install --prefix ./.mcp-servers <pkg>@<exact-version>` (exact → re-run no-op), ghi `*_MCP_DIST` khi thiếu (no-clobber M26), health-gate [7/7] source-aware. `--mcp-dev` giữ clone+build cũ. **Migration F5**: máy cũ có `*_MCP_DIST` trỏ build thấp hơn min → cảnh báo + hướng dẫn (không tự sửa .env). `version_lt` qua `sort -V` (semver-đúng: 4.2.0 < 4.10.0). bash 3.2 compat. Kích hoạt sau khi publish xác nhận (`MCP_NPM_PUBLISHED=1`).
- **Enforce min-version mặc định** (P3 để warn-only tới khi publish): giờ raise nếu server < min, escape `MCP_MIN_VERSION_ENFORCE=false`. Server đúng version (= min) pass (>= không phải >). Server lạ (Linear) / version None / unparseable → không raise.
- **Docs**: getting-started + huong-dan-su-dung A.2 + deployment-production → npm mặc định, `--mcp-dev` dev. Repo jira README ghi mapping pkg-name ≠ repo-name.

## Verified

- `npm view` 3 pkg = 4.2.0/1.5.0/1.3.0.
- **Live: `npm install --prefix` fresh** (132 pkg, 3s) → 3 entry file present; **slack bundle npm-installed spawn + serverInfo 1.3.0 + real whoami team MPM** — toàn bộ đường publish→install→spawn→API thật chạy.
- `version_lt` semver-đúng; docs không còn caveat "chưa publish"; `bash -n` OK dưới /bin/bash 3.2.
- **1233 test** (thêm enforce-default tests) + ruff sạch.
- Code-review DONE_WITH_CONCERNS → vá: comment install.sh mâu thuẫn (leftover trạng thái publish-blocked) + strip phase-label khỏi comment (rule review-audit-self-decision).

## Bài học

- **Comment leftover từ trạng thái tạm = mâu thuẫn nguy hiểm**: subagent viết "publish BLOCKED, registry serves OLD" rồi lại "packages published" cùng block — review bắt. Khi trạng thái đổi (blocked→done), phải dọn comment cũ.
- **Flip default enforce phá test fixture**: fake client default version thấp hơn min → enforce-default raise ở test không liên quan version. Fixture phải version cao (999.0.0) để test cơ chế tách khỏi version-gating.
- **esbuild ESM + winston OK**: lo winston dính bundle nhưng không — test stdio thật từng server là gate đúng.

## v11 HOÀN TẤT — tổng kết

3 MCP server + adapter my-pm giờ là 1 bộ đồng bộ:
- **Nhanh hơn**: Confluence bỏ boot network-call (134ms), Slack cache (cold 363ms→warm 2ms), session-reuse (weekly 5 spawn→2, −43%), bundle single-file.
- **Đáng tin hơn**: Slack whoami + TOKEN_EXPIRED (failure-mode vận hành #1 chẩn đoán được), 429 retry, health probe sống.
- **Đồng bộ**: SDK pin 1.17.4 cả 3, serverInfo=package.json, version contract enforce, stdin-EOF cả 3 (lưới an toàn cho session-reuse: SIGKILL parent → 0 orphan).
- **Cài tiện**: npm install mặc định (không cần build toolchain), `--mcp-dev` cho dev.
- **Gọn hơn**: jira node_modules 122M→80M, slack −4–5k LOC chết.

Commit: P1 `d0f8506` · P2 `609dcf2`/`9b09bc5` · P3 `f76734a` · P4 servers `955d303`/`6fa3223`/`2ecc3d1` + my-pm (commit này). Test my-pm 1233 pass. THE INVARIANT nguyên vẹn (session-reuse là tầng transport, gateway verdict flow không đổi).

## Unresolved

- Latent (không chặn): allowlist my-pm `addcomment` vs server `addIssueComment` — my-pm chưa gọi jira addComment ở flow nào; khớp tên nếu sau giao việc tạo comment jira.
