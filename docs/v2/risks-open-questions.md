# v2 — Risks + Open Questions

> Cross-cutting, hay cập nhật. Quay lại [README](README.md).

## 9. Risks + open questions

1. **Secrets cho nhiều agent** — ✅ CHỐT: **giữ `.env`** (user quyết — chưa làm secret store riêng). `profile.yaml.bindings.*.token_env` chỉ tham chiếu *tên* env var; giá trị thật ở `.env` toàn cục (1 file, nhiều token, mỗi binding trỏ tên khác nhau). Token KHÔNG nằm trong profile (an toàn để versionable). Residual: `.env` phình khi nhiều agent, và "Atlassian token pattern-undetectable" (v1 đã chấp nhận) — không đổi. Nếu sau cần versionable/multi-machine, nâng lên SOPS/Vault là *thêm 1 backend cho `token_env` resolver*, không đổi profile schema (để ngỏ, không làm bây giờ — YAGNI).
2. **Postgres — M1 hay M2?** Đề xuất **M2-P8, opt-in**. M1 dùng SqliteSaver per-agent (1 process/agent → không tranh chấp). Confirm: có use case multi-machine nào ở M1 không? Nếu không, hoãn Postgres là đúng (YAGNI).
3. **HTMX vs Streamlit** — chưa chốt (P7). HTMX nếu streaming live (P6 SSE) là must; Streamlit nếu dựng nhanh + chấp nhận poll. Quyết sau P6.
4. **Interrupt replace hay coexist với queue Lớp B?** P5 đề **augment** (cả hai), replace ở P8 khi Postgres bền resume xuyên process. Confirm: approval async (duyệt sau vài giờ) chấp nhận giữ graph paused + checkpoint, hay vẫn cần queue tách rời?
5. **Resource cost process-per-agent** — N agent = N Python process + N node MCP subprocess spawn/run. 5 agent OK; 50 agent cần worker pool / share. Quyết khi P3 đo RAM/process thật. Mitigation M1: worker on-demand/scheduled, không thường trực.
6. **Persona override an toàn** — body profile override prompt; phải KHÔNG đè được external-prompt sanitization (rò PII — bài học Phase 5). P2 acceptance test bắt buộc: external + persona vẫn zero key/PII.

---

> **Cook order**: M1 P1→P2→P3→P4 (mỗi cái chạy được), rồi M2 P5→P6→P7→P8. P1 BREAKING — cook trước hết. `default` profile (P2) là lưới an toàn migrate v1.
