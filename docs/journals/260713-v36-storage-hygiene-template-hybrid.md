# v36 — Storage hygiene + template hybrid update
2026-07-13 · ✅ Done (2149 BE + 200 FE)

Backlog #1+#2 từ brainstorm mgmt 260713. 3 phase, cook 1 phiên, review Sonnet bắt 1 HIGH thật.

## Làm gì
- **P1 Storage hygiene**: GC theo tuổi cho 4 store phình vô hạn — captures 180d, office_room 90d, clarify 90d (chỉ answered/expired, pending không đụng), dedup 7d. Kèm `schema_meta` version (4 store team-side) + integrity audit read-only daily-gated. Wire best-effort vào team-tick hygiene block (`storage_hygiene.py`).
- **P2 Template live-skills**: agent tạo từ template ghi `template_role`, skill load THẲNG từ `profiles/templates/<role>/skills/` lúc chạy (repo-vetted, không copy). Sửa skill template → cả đội role đó nhận ngay. Agent-own trùng tên thắng; xoá `_copy_template_skills`. Agent cũ (không có template_role) byte-identical.
- **P3 Template config version-pin**: template.yaml có `version`; create lưu `template_version` + `template_config_applied` (baseline). Badge "bản mới" trang Đội + dialog nâng cấp có duyệt (`template_upgrade.py` + 3 route + FE). Chỉ áp field user chưa sửa (live==baseline), field user sửa → giữ + báo; backup `profile.yaml.bak-<ts>` trước mọi ghi, apply qua save-door validate.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| 9-DB split GIỮ nguyên, chỉ thêm GC/version/audit | Researcher: split coherent (lock-decoupling/langgraph-owned/per-agent); gộp lợi ít risk lớn | Vẫn 9 file backup |
| Skills live-load, config version-pin (hybrid Option 3) | CEO chốt: skill = 1 nguồn sự thật 0 drift; config nâng có duyệt vì đổi ít + cần an toàn | 2 cơ chế khác nhau cho skill vs config |
| GC theo tuổi (không cap số lượng); giữ lâu (180/90) | CEO "giữ lâu hơn" — audit-friendly, vẫn có trần | DB to hơn cap-số |
| `domain` KHÔNG nằm trong field nâng cấp | Đổi domain cần re-validate reports/bindings — không phải auto-apply an toàn | Đổi domain vẫn phải tạo lại/sửa tay |
| template_config_applied baseline trong profile | Cần biết "user đã sửa field chưa" mà không giữ lịch sử version cũ | Agent pre-P3 thiếu baseline → coi mọi field user-sửa (an toàn: không áp gì) |

## Vấp & học được
- **Review HIGH thật**: `storage_hygiene` dùng `datetime.now()` naive trong khi mọi store ghi `datetime.now(UTC)` aware → cutoff lệch múi giờ, dedup 7d bị xoá sớm ~7h. Đây là call-site naive DUY NHẤT trong src. Sửa → `datetime.now(UTC)`.
- Reviewer subagent Fable hết hạn mức giữa chừng (lần v35) → lần này override model=sonnet, chạy trọn.
- "Validate door" của `save_profile_yaml` yếu hơn plan tưởng (chỉ validate settings/reporting/inbox, không validate report-kind-vs-pack) → viết lại test P3 cho đúng bảo đảm THẬT: apply đi qua save-door + backup-trước-ghi (không phải "reject mọi config hỏng").
- Dọn 1 orphan `vai-thu` trong registry.yaml (rò rỉ từ test chạy trước khi fix isolation) — registry.yaml là user-data gitignored, sửa trực tiếp (không git checkout).

## Mở / sang sau
- FE badge/dialog nâng cấp chưa có test riêng (overlay mỏng, tsc+vitest xanh).
- template_role guard hiện là denylist (verified không exploit) — có thể siết allowlist regex sau.
- Retention theo tuổi cố định hằng số; nếu cần cap-số hoặc config runtime thì thêm sau.
