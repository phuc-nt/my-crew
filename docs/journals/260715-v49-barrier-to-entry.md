# v49 — barrier-to-entry: quickstart + coordinator-in-crew + keepable starter
2026-07-15 · ✅ Done

## Làm gì
- **`mpm quickstart`** — chỉ cần OPENROUTER_API_KEY → chạy report `daily` agent `default` DRY-RUN (ép cứng, không ghi ngoài). Thiếu key → hint + exit 2. Thin dispatch qua `run_agent` sẵn có.
- **`mpm crew init`** — scaffold đội mẫu THẬT giữ lại (reuse v32 `create_crew`, idempotent skip-existing), khác demo-mode swap tạm. In summary + next-step.
- **`<CoordinatorHealthBanner />` lên màn Đội** — sau khi tạo đội, hiện trạng thái điều phối + lệnh khởi động nếu chưa chạy (DRY: tái dùng banner office-unified, poll `/health/coordinator` sẵn có).
- Cả 3 gói trong module mới `mpm_onboarding_cmds.py`; doc §3b "Quick-start 30 giây".

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Compose + doc, KHÔNG build init-wizard/preset/dual-mode mới | Scout code: máy-móc onboarding ĐÃ có (wizard v17, one-click crew v32, demo-mode); research đề CLI mới = TRÙNG | 0 — thuần thêm |
| BÁ A3 (default enabled) | Ship default đã đúng (`registry.example.yaml` enabled:true, bootstrap registry.py:9); `false` local là user-data gitignored v18 KHÔNG được chạm | — |
| quickstart ép `--dry-run` cứng | first-taste an toàn tuyệt đối, không đường ghi ngoài | không chạy live được (đúng ý — muốn live thì `mpm agent run`) |
| Coordinator: hint-only ở dev, KHÔNG auto-spawn từ web-request | spawn daemon từ HTTP handler = orphan/dup ticker | user phải chạy 1 lệnh (đã surface + doc) |
| crew init reuse `create_crew` verbatim | DRY — cùng 1 cửa với web one-click | — |

## Vấp & học được
- Report 3-harness khuyên "config nặng" — nhưng đọc code cho thấy cấu trúc config **tự-cấp gần hết** (registry bootstrap, company degrade, profile default, 8-agent team ship sẵn). Bias đánh-giá-qua-CLI của report (họ tự nhận §6). Bài học: **verify code trước khi nhận lời khuyên external**, barrier thật hẹp hơn nhiều.
- Research subagent (không đọc repo) đề `my-crew init`/`--preset`/`crew-definition.yaml` — trùng cái đã có. Giá trị research = xác nhận NGUYÊN TẮC (progressive-disclosure, safe-default, opt-in-prod) my-crew đã theo, KHÔNG phải blueprint.
- Phase 2 hoá ra trivial: `CoordinatorHealthBanner` đã tồn tại (office-unified), chỉ cần render thêm ở Đội — DRY tuyệt đối, 0 component mới.

## Mở / sang sau
- Nút "khởi động điều phối" launchd (kickstart như routes_setup.py:182) để ngỏ — MVP là hint.
- Report còn #2b Seatbelt (đã bác có lý), #6 rate-limit config, #7 (v49 đã chạm một phần barrier).
