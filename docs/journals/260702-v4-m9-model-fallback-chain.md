# v4 M9 — Multi-provider fallback chain
2026-07-02 · ✅ Done

Agent không chết vì 1 model lỗi nữa: khai báo `model_chain: [primary, fallback…]` → 402/429/5xx/timeout/empty tự chuyển model kế, có log lớn tiếng. Không khai báo → byte-identical như cũ. Mốc đầu v4 (resilience) — điều kiện để agent "thay người" đáng tin.

## Làm gì
- **`fallback_policy.py`** — bảng quyết định thuần: APIStatusError (trừ 401/403) / timeout / connection / retries-exhausted / empty-content → thử model kế; **BudgetExceededError / 401/403 / lỗi lạ → raise thẳng** (lỗi key-level thì đổi model vô ích; budget cap tối thượng không được "lách" bằng fallback).
- **Chain nằm TRONG `LlmClient.complete`** (as-built gọn hơn plan — plan định tách ModelChain wrapper + sửa call sites): `settings.effective_model_chain()` = chain khai báo hoặc `(model,)`. Kết quả: **0/9 call site phải sửa**, `model=` tường minh vẫn bypass chain.
- **Budget cap tối thượng**: `check_allowed()` re-check trước MỖI attempt; cost mọi attempt billed đều ghi. Không reorder chain theo giá (không có bảng giá — operator tự xếp thứ tự, ghi rõ deviation).
- **Observability**: WARNING `FALLBACK: model X failed … trying Y` + `served by Y after [X]` + field mới `LlmResult.fallback_from` (đuôi tuple, default rỗng — mọi test double cũ vẫn chạy). Run-event integration defer: single-operator đọc log service/cron là đủ.
- Config: profile `model_chain:` (list) > env `OPENROUTER_MODEL_CHAIN` (comma) > không có (1 model). Fail-loud lúc load: entry không phải string (yaml `2.5` không quote) raise ngay, không đợi cron 3h sáng.

## Review (DONE_WITH_CONCERNS → vá trong milestone)
- **M1** docstring hứa fail-loud nhưng code `str()`-coerce entry lạ → vá: raise + test.
- **M2** chain override `model:` âm thầm (env chain cũ quên unset → model cũ phục vụ mãi) → vá: WARNING "model_chain overrides configured model".
- **L1** nhánh raise cuối unreachable gợi contract sai → đổi `AssertionError` unreachable; exhaustion = lỗi thô của model cuối propagate.
- **M3** (ghi nhận, không vá): worst-case stall × chain length (~3 phút/model) — docstring cảnh báo giữ chain 2-3 model.

## Verified
885 pytest (22 mới) + ruff clean. **E2E live**: `OPENROUTER_MODEL_CHAIN="openrouter/no-such-model,minimax/minimax-m2.7"` chạy `report --daily` → primary 400 invalid-model → 2 dòng FALLBACK trong log → minimax trả prose → report delivered ($0.0019, DRY_RUN nên không post; approval E2E đã reject dọn sạch).

## Bài học
- Đặt fallback ở tầng client (dưới mọi call site) rẻ hơn hẳn wrapper mới + rewire: quyết định "ai sở hữu retry policy" nên nằm cạnh chỗ sở hữu retry sẵn có.
- Phân loại lỗi theo "đổi model có giúp không" (model-level vs key-level vs budget) rõ hơn liệt kê status code.
- `RuntimeError` chung chung không phân biệt được "retries exhausted" với "thiếu API key" — subclass (`ProviderCallError`) là chi phí 3 dòng để policy không fallback nhầm trên lỗi cấu hình.
