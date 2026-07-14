"""The deepagents work loop for the deep-agent runtime (v20.5 Phase 3).

Runs `create_deep_agent` whose shell/`execute` is bound to a token-free sandbox backend
(Docker self-hosted, or fake for tests). Returns `(result_text, cost)` matching the
`TeamTaskDeps.run_work` contract, so the surrounding team-step graph (self_check / rework /
deliver → external_write → gateway from Phase 0) is untouched.

Safety wiring (all red-team fixes converge here):
- **Sandbox-only shell** (C2/C3): `backend=` is our fail-closed sandbox; no backend ⇒ SandboxDenied.
- **PII gate** (H2/H3): the context is stripped to external-audience-safe before it reaches the
  agent, so internal memory/company_docs cannot be exfiltrated from the sandbox.
- **Loop cap** (C5): `recursion_limit` is bound to the runtime's `runtime_loop_limit`.
- **Teardown** (C6): the sandbox is torn down on the normal path (best-effort; the container's
  own idle ceiling is the SIGKILL backstop).
- **Built-in tools confined** (H4): deepagents' write_file/execute/subagent tools all operate
  THROUGH the sandbox backend — they touch the container, never the host or the gateway. The
  step's only company egress is the text result → deliver → gateway.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Appended to the deep_agent system prompt so a research-heavy run writes its report to a file
#: EARLY (as soon as it has one pass of sources) and refines in place, instead of researching
#: until the bounded recursion loop is exhausted and never reaching the final write. The read-back
#: (`_merge_sandbox_artifacts`) then always finds a report even if the loop is cut mid-refine.
_DEEP_AGENT_COMPOSE_CONTRACT = (
    "\n\nQUY TẮC VIẾT BÁO CÁO (bắt buộc): NGAY khi bạn đã có một vòng thu thập nguồn đủ dùng, "
    "hãy viết BẢN NHÁP báo cáo ra một file .md trong /work TRƯỚC (dùng write_file), rồi mới bổ "
    "sung/tinh chỉnh file đó ở các vòng sau. TUYỆT ĐỐI không dồn hết các vòng cho việc tra cứu rồi "
    "mới viết ở cuối — vòng lặp có giới hạn, nếu để tới cuối bạn có thể hết lượt trước khi kịp ghi "
    "báo cáo. Luôn đảm bảo /work có một file .md chứa báo cáo hiện tại ở mọi thời điểm."
)

#: v43: hard cap on how many `task` delegations one deep_team run may make. deepagents has no
#: built-in delegation-count knob, so `TaskCapMiddleware` enforces it in code; the prompt clause
#: below advises the SAME number so the model rarely hits the hard refusal. Bounds wall-time: each
#: subagent runs its own fresh recursion budget, so N unbounded delegations could exceed the
#: sandbox container lease (SANDBOX_LEASE_S) and be SIGKILL'd mid-compose.
_MAX_TASK_CALLS = 3

#: v43: appended to the TOP-LEVEL deep_agent prompt only when deep_team is on. Tells the agent it
#: MAY delegate independent, context-heavy sub-questions to the `task` tool — bounded to
#: `_MAX_TASK_CALLS` — and that each subagent must leave its output in /work/<name>.md so the
#: parent's read-back (`_merge_sandbox_artifacts`) captures it even if the run is cut short.
_DEEP_TEAM_DELEGATION_CLAUSE = (
    "\n\nPHỐI HỢP TRỢ LÝ CON (tùy chọn): với các câu hỏi con ĐỘC LẬP cần ngữ cảnh lớn riêng biệt "
    f"(ví dụ mỗi nguồn phân tích tách bạch), bạn CÓ THỂ giao cho công cụ `task` — tối đa "
    f"{_MAX_TASK_CALLS} lần. Mỗi trợ lý con PHẢI ghi kết quả ra một file /work/<tên-riêng>.md "
    "(tên khác nhau, tránh ghi đè) rồi bạn tự tổng hợp báo cáo cuối. Nếu việc đơn giản, cứ tự "
    "làm — đừng giao khi không cần."
)

#: v43: system prompt for the curated `general-purpose` subagent. Carries the SAME compose-early
#: discipline as the parent (v42), one level down: a subagent that researches into its own loop cap
#: and never writes a file produces nothing the parent can read back.
_DEEP_TEAM_SUBAGENT_PROMPT = (
    "Bạn là trợ lý con được giao một câu hỏi con cụ thể trong một nhiệm vụ lớn hơn. Làm đúng "
    "trọng tâm câu hỏi được giao, dựa trên dữ liệu bạn thu thập được. "
    "QUY TẮC (bắt buộc): NGAY khi có đủ một vòng thông tin, ghi kết quả ra một file "
    "/work/<tên-riêng>.md (tên gợi nhớ, KHÁC các file đã có để tránh ghi đè) rồi tinh chỉnh — "
    "đừng dồn hết vòng lặp cho tra cứu rồi mới ghi ở cuối. Trả về tóm tắt ngắn gọn kết quả của bạn."
)


def _deep_team_subagents() -> list[dict]:
    """v43: the declarative `SubAgent` spec(s) passed to create_deep_agent when deep_team is on.

    ONLY declarative specs (name/description/system_prompt) — NEVER a CompiledSubAgent runnable or
    AsyncSubAgent. A declarative spec has no `backend` field, so deepagents forces it through the
    parent's exact sandbox backend (FilesystemMiddleware(backend=backend)); this is what keeps the
    moat: a subagent's shell/file ops route through the same sandbox, and its only egress is text
    the parent folds into its own result → deliver → gateway. Keep this a single general-purpose
    subagent (YAGNI): role-flavored specs add config surface for no proven need.
    """
    return [
        {
            "name": "general-purpose",
            "description": (
                "Trợ lý con đa năng: nhận một câu hỏi con độc lập, thu thập/phân tích trong ngữ "
                "cảnh riêng, ghi kết quả ra /work/<tên>.md và trả về tóm tắt."
            ),
            "system_prompt": _DEEP_TEAM_SUBAGENT_PROMPT,
        }
    ]


def run_deep_agent_work(
    *, title: str, handoff: str, context, settings, sandbox_cfg, loop_limit: int,
    telemetry=None, sanitize=None, deep_team: bool = False,
) -> tuple[str, float | None]:
    """Run one team-step's work as a deepagents loop inside a hardened sandbox.

    `telemetry` (optional StepTelemetry) receives summed token counts + cost provenance;
    cost still returns on the tuple. Absent collector = no-op (byte-identical behavior).

    `sanitize` (optional Sanitizer) redacts internal-sensitive tokens from the agent's input
    (context fields + handoff) before it reaches the sandbox prompt; defaults to an LLM sanitizer
    built from `settings`. If sanitization fails, the sandbox is forced network-OFF so
    un-sanitized internal data can never egress — the sanitizer is the trust boundary that makes
    a network-on deep_agent safe.

    `deep_team` (v43, opt-in): when True, the agent may delegate independent sub-questions to
    in-sandbox subagents via deepagents' built-in `task` tool. A curated general-purpose subagent
    spec (compose-early), a hard delegation cap (`TaskCapMiddleware`), and a usage-metadata callback
    (folds subagent tokens into the step cost) are wired only in this branch. Subagents inherit the
    parent's exact sandbox backend, so their file/shell ops stay confined and their only egress is
    text folded into the parent's result → deliver → gateway (THE INVARIANT holds). False (default)
    ⇒ byte-identical to pre-v43.
    """
    from deepagents import create_deep_agent
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    from src.config.settings import OPENROUTER_BASE_URL
    from src.llm.team_task_prompt import build_team_step_messages
    from src.runtime_backends.community_loop_core import invoke_capped, record_loop_result
    from src.runtime_backends.deep_agent_sanitizer import make_llm_sanitizer, sanitize_bundle
    from src.runtime_backends.sandbox_backend import build_sandbox_backend
    from src.runtime_backends.sandbox_teardown import teardown_sandbox

    # Sanitize the internal input channels (context fields + handoff) BEFORE deciding on network:
    # the network flag is ANDed with sanitize success, so an opt-in only takes effect on a clean
    # bundle. Persona (SOUL.md) is sanitized too — it can name real people. company_docs withheld.
    if sanitize is None:
        from src.llm.client import LlmClient
        sanitize = make_llm_sanitizer(LlmClient(settings))
    bundle, sanitize_ok = sanitize_bundle(
        sanitize,
        persona=getattr(context, "persona", "") or "",
        project=getattr(context, "project", "") or "",
        memory=getattr(context, "memory", "") or "",
        capability=getattr(context, "capability", "") or "",
        handoff=handoff or "",
    )

    # Network AND-gate: opt-in ONLY takes effect when the input was sanitized. On failure, force
    # network off via an adjusted per-run cfg (reuses Phase 2's cfg.get("network") seam).
    net_opt_in = bool((sandbox_cfg or {}).get("network"))
    effective_network = net_opt_in and sanitize_ok
    run_cfg = {**(sandbox_cfg or {}), "network": effective_network}

    # Fail-closed: raises SandboxDenied on None/local/unknown (red-team C3). The shell has no
    # backend to run on otherwise — deepagents' execute returns an error, but we refuse earlier.
    backend = build_sandbox_backend(run_cfg)

    msgs = build_team_step_messages(
        step_title=title, handoff_context=bundle.handoff,
        persona=bundle.persona, project=bundle.project,
        memory=bundle.memory, capability=bundle.capability,
    )
    system = next((m["content"] for m in msgs if m["role"] == "system"), "")
    # Step-budget contract (deep_agent only): research tasks that fetch many sources can
    # exhaust the bounded recursion loop BEFORE reaching the final write_file, losing the
    # report entirely (~25% of benchmark runs stalled at "Let me compile the report"). Bind
    # a compose-early discipline so the report exists as a file well before the loop cap —
    # cheaper and safer than raising the cap (the bounded loop stays a red-team guardrail).
    # deep_agent-only: it is the sole tier with a sandbox + write_file; native/create_agent
    # have no file to write, so this rides here rather than in the shared team-step prompt.
    system = system + _DEEP_AGENT_COMPOSE_CONTRACT
    # v43: when deep_team is on, tell the top-level agent it may delegate independent sub-questions
    # to the `task` tool (bounded), and each subagent must write /work/<name>.md.
    if deep_team:
        system = system + _DEEP_TEAM_DELEGATION_CLAUSE
    user = next((m["content"] for m in msgs if m["role"] == "user"), title)

    model = ChatOpenAI(
        model=settings.openrouter_model,
        api_key=settings.openrouter_api_key,
        base_url=OPENROUTER_BASE_URL,
    )
    # v43: build the deep_team wiring only when opted in. `subagents` = one curated general-purpose
    # spec (compose-early, sandbox-confined by construction); `middleware` = a hard cap on `task`
    # delegations. `usage_handler` captures BOTH parent and subagent tokens (subagent AIMessages
    # never bubble into the parent's returned messages, so record_loop_result would otherwise
    # under-count them → v26 cost-honesty). None on all three ⇒ pre-v43 behavior, byte-identical.
    extra_agent_kwargs: dict = {}
    usage_handler = None
    if deep_team:
        from langchain_core.callbacks import UsageMetadataCallbackHandler

        from src.runtime_backends.deep_team_task_cap import TaskCapMiddleware

        extra_agent_kwargs["subagents"] = _deep_team_subagents()
        extra_agent_kwargs["middleware"] = [TaskCapMiddleware(max_calls=_MAX_TASK_CALLS)]
        usage_handler = UsageMetadataCallbackHandler()
    try:
        # Shell tier binds the system prompt on the agent AND sends it as a SystemMessage (its
        # built-in tools read the bound prompt); both derive from the sanitized bundle.
        agent = create_deep_agent(
            model, backend=backend, system_prompt=system, **extra_agent_kwargs
        )
        result = invoke_capped(
            agent,
            [SystemMessage(content=system), HumanMessage(content=user)],
            recursion_limit=max(2, loop_limit * 2),  # bounded loop
            usage_handler=usage_handler,
        )
        text, cost = record_loop_result(
            result, model_name=settings.openrouter_model, telemetry=telemetry,
            usage_handler=usage_handler,
        )
        # v41: the agent often writes its report to a /work/*.md file instead of (or as well
        # as) the reply text. Read those back BEFORE teardown removes the container, appending
        # any content not already in the reply — else the report is lost with the container.
        text = _merge_sandbox_artifacts(backend, text)
        return text, cost
    finally:
        teardown_sandbox(backend)  # C6: best-effort container teardown on the normal path


#: Cap on total artifact text appended to the reply — keep the delivered/audited result bounded.
_ARTIFACT_MERGE_MAX_CHARS = 256_000


def _merge_sandbox_artifacts(backend, text: str) -> str:
    """Append `/work/*.md` artifacts the agent wrote to `text` (before teardown), skipping any
    already present in the reply. Best-effort: any failure leaves `text` unchanged — the reply
    is the primary result, the file read-back is a supplement."""
    try:
        listing = backend.execute("ls /work/*.md 2>/dev/null")
        names = [n.strip() for n in (getattr(listing, "output", "") or "").split() if n.strip()]
        if not names:
            return text
        pieces: list[str] = []
        budget = _ARTIFACT_MERGE_MAX_CHARS - len(text)
        for name in names:
            if budget <= 0:
                break
            got = backend.download_files([name])
            if not got or got[0].error is not None or got[0].content is None:
                continue
            try:
                body = got[0].content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            # Skip a file whose content is already substantially in the reply.
            if body.strip() and body.strip()[:200] not in text:
                header = f"\n\n### Artifact: {name}\n"
                snippet = body[: max(0, budget - len(header))]
                block = header + snippet
                pieces.append(block)
                budget -= len(block)
        return text + "".join(pieces) if pieces else text
    except Exception:  # noqa: BLE001 — read-back is a supplement; never fail the run
        logger.warning("deep_agent artifact read-back failed (ignored)", exc_info=True)
        return text
