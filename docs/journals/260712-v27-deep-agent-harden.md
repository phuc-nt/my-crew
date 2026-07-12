# v27 — deep-agent-harden (vá đánh giá bảo mật bên thứ 3)
2026-07-12 · HOÀN TẤT (1863 BE + 178 FE xanh, ruff/tsc sạch; live Docker UAT: container harden + reaper nano-timestamp thật; code-review SHIP)

## Làm gì
Vá 7 finding (F1-F7) từ đánh giá bảo mật bên thứ 3 (`docs/research/deep-agent-safety-checklist-v205-v26.md`) — CHỈ đụng deep_agent path + model_pricing + wizard; native/tool-calling/capture nguyên vẹn.
- **Sanitize-at-source** (`deep_agent_sanitizer.py`, thay `deep_agent_pii_gate.py` đã xoá): LLM sanitize-pass làm sạch **5 kênh** (persona/project/memory/capability/handoff) trước khi vào sandbox — deep_agent giữ grounding đầy đủ nhưng sạch. `handoff` là kênh red-team chứng minh rò (dep result + consult SOUL/PROJECT) mà gate cũ bỏ sót.
- **Network AND-gate fail-closed**: `effective_network = opt_in AND sanitize_ok`. Sanitize lỗi → network OFF bất kể opt-in. Network mặc định TẮT, opt-in per-agent `sandbox:{network:true}`.
- **Container harden** (`sandbox_backend.py`): `cap_drop=ALL`/`no-new-privileges`/`user=nobody`/network = HARD (fail-closed nếu daemon reject); `mem_limit`/`pids_limit`/`read_only`/`tmpfs(1777)` = degradable (loud WARNING, 1 retry). HOME=/work chỉ docker env (không đụng `_scrubbed_sandbox_env` shared).
- **Reaper** (`sandbox_reaper.py` + ticker `run_tick`): container `sleep 600`+`auto_remove`+label `mycrew-sandbox`; reaper sweep xoá orphan còn-chạy age>TTL+grace (grace=2*tick+60), `docker.from_env(timeout=5)`, best-effort never-raise.
- **F4/F7/F5/F6**: doc recursion_limit=loop_limit*2 + test; price guard `isfinite and >=0` (nan/inf/âm→None); wizard emit deep_agent mapping `{kind,sandbox}` + `agent_create.py` nhận mapping; docstring `fake|modal|e2b`→`fake|docker`.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Sanitize-at-source thay strip-project | F1 gốc chỉ strip context, handoff rò thẳng (red-team C1) → strip không đủ | Thêm LLM sanitize-pass/step; recall không exhaustive (residual Q4) |
| Sanitize CẢ persona (5 kênh) | SOUL.md có thể tên người thật (context.py); "no PII by contract" không enforce (code-review LOW) | Persona qua sanitize có thể nhạt role-framing |
| Fail-closed → network OFF khi sanitize fail | Không bao giờ raw data vào sandbox network | Sanitize down → deep_agent mất web (chấp nhận, an toàn > tiện) |
| HARD vs degradable tách nhóm | Degrade-bundle gộp làm rớt cap_drop khi Docker quirk (red-team H1) → container root+network-off | Reject HARD kwarg = fail-closed (deep_agent không chạy trên daemon đó) |
| Network default OFF | deep_agent shell không cần web (scrape đi qua tool-calling/Firecrawl) | Opt-in thủ công khi thật cần |

## Vấp & học được
- **Live UAT bắt lỗi ngay khi cook (không đợi Phase 6)**: container `nobody`+`read_only`+tmpfs mặc-định-root → `cannot create /work/x.txt: Permission denied` (test docker live fail). Fix: tmpfs `mode=1777` (sticky world-writable) → nobody ghi được, read_only giữ rootfs bất biến. Bài học: harden non-root PHẢI kèm writable scratch đúng mode.
- **H2 CI-green-prod-dead verify bằng container THẬT**: Docker `Created` nano-giây 9 chữ số phá `fromisoformat`. `_parse_docker_created` truncate nano→micro; UAT spawn container thật (`Created=...213170668Z`) → reaper parse + xoá được. Nếu chỉ test timestamp giản lược sẽ xanh giả.
- **Fail-closed 3 đường đều an toàn** (code-review trace): sanitize-fail→network off; degrade-fail→SandboxDenied; sanitize-RAISE→propagate out, step chết TRƯỚC build_sandbox_backend (không network-on). Raise cũng fail-safe.
- **docker inspect chứng minh harden thật**: CapDrop=[ALL], SecurityOpt=[no-new-privileges], ReadonlyRootfs=True, User=nobody, NetworkDisabled=True, PidsLimit=256 trên container thật.

## Mở / sang sau
- **Sanitizer recall không provable** (Q4): Phase 6 check marker không exhaustive — bounded bởi network-off-on-fail + opt-in-off-default. Residual chấp nhận.
- **F8 (cost)** đã vá v26 (không thuộc v27).
- Giá `config/model_prices.yaml` vẫn placeholder (v26) — operator verify.
