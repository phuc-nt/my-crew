# DeepAgent safety checklist (v20.5 + v26)

**Ngày:** 2026-07-12 · Đánh giá độc lập v20.5 (runtime-tiers/sandbox) + v26 (telemetry/cost).
**Bối cảnh:** tất cả finding CHỈ liên quan **DeepAgent** (nhân sự chạy code trong sandbox, đang experimental + fail-closed). Native + tool-calling engine KHÔNG dính. Egress ra ngoài vẫn qua Action Gateway. **Không finding nào chặn giữ code trên main.** Cần vá TRƯỚC khi bật DeepAgent chạy việc thật.

**Trạng thái test:** 1842 pass, 0 fail (committed HEAD `50f9940`). Working tree sạch.

## Checklist

| # | Vấn đề (1 câu) | Mức | Trạng thái | Fix |
|---|---|---|---|---|
| **F1** | Quên thu file `PROJECT.md` (nội bộ) trước khi đưa vào sandbox có mạng → rò dữ liệu dự án. Chạm invariant #2. | 🔴 Cao | ❌ Chưa | Strip thêm `project` (+ `sibling_facts`) trong `deep_agent_pii_gate.gate_context_for_sandbox` + thêm test. Rẻ (1 dòng). **Ưu tiên #1.** |
| **F2** | Sandbox còn internet (`network_disabled=False`) + chạy root, không giới hạn quyền/RAM/CPU → SSRF/exfil/DoS. | 🟠 Cao | ❌ Chưa | `network_disabled=True` mặc định, `cap_drop=[ALL]`, non-root, `mem_limit`/`pids_limit`, `no-new-privileges`, `read_only`+tmpfs. |
| **F3** | Worker bị kill (hết lease 600s) → container không được dọn, chất đống ~1h → cạn tài nguyên. | 🟠 Cao | ❌ Chưa | `auto_remove=True` + self-kill ≤ lease + reaper theo label do ticker chạy. |
| **F4** | Loop cap ×2 âm thầm (16→32), test chỉ assert ở config, không ở invoke. | 🟡 TB | ❌ Chưa | Document `*2`; thêm test recursion_limit truyền vào `invoke`. |
| **F5** | Wizard web tạo DeepAgent thiếu block `sandbox:` → agent fail-closed mọi tick (DOA). UX vỡ, không nguy hiểm. | 🟡 TB | ❌ Chưa | Wizard tự gắn `sandbox:{provider:docker}` khi chọn deep_agent, hoặc bỏ recommend. |
| **F6** | Doc drift: `config.py` docstring ghi `fake\|modal\|e2b`, thật là `fake\|docker`. | 🟡 Thấp | ❌ Chưa | Sửa docstring. |
| **F7** | `model_pricing`: giá âm/non-numeric trong YAML → raise thay vì degrade. | 🟢 Thấp | ❌ Chưa | Wrap `float()` → None. |
| **F8** | DeepAgent không tính cost (return None) → không có trần per-task. | 🟠 Cao | ✅ **Đã vá (v26)** | `estimate_cost` token×giá, unified 3 engine, provenance exact/estimated/None. |

## Tóm tắt
- **Đã vá:** F8 (cost, v26).
- **Còn:** F1–F7 — trong đó **F1 nên đẩy lên trước** (rẻ + chạm invariant #2), rồi F2/F3 (harden container) trước khi DeepAgent chạy untrusted task thật.
- Native/tool-calling engine an toàn, không dính F nào.

## 3 câu hỏi mở
1. Sandbox mở internet là chủ đích (research cần web) hay sót? → quyết định F2 network-default.
2. CI có chạy `test_sandbox_docker_live.py` không hay luôn skip (không Docker)? → nếu skip, bằng chứng OS-isolation chỉ thủ công.
3. DeepAgent định no-cost-attribution khi ship hay v26 đã đóng hẳn F8? (v26 đã có estimate — xác nhận đủ chưa.)
