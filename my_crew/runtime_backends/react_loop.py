"""The tools-tier work loop — a community-standard `langchain.agents.create_agent` loop.

Runs `langchain.agents.create_agent` (langchain 1.x) over the policy-shimmed read toolset, with
a hard per-loop step cap. Returns `(result_text, cost_usd)` matching the `TeamTaskDeps.run_work`
contract, so the surrounding team-step graph (self_check / rework / deliver→gateway) is untouched.

Tools are LangChain `@tool` callables wrapping the read allowlist; the model may call them in
a loop but can never reach a write — the toolset contains only reads. The cap and the
overflow-degrade + tracing-off live in `community_loop_core.invoke_capped`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

#: Per-tool description so the model passes the RIGHT argument (e.g. a URL for web.scrape, not
#: the question text). Falls back to a generic read description for unlisted tools.
_TOOL_DESCRIPTIONS = {
    "web.scrape": "Đọc TOÀN BỘ nội dung của MỘT URL web công khai (http/https) và trả về "
                  "markdown. Tham số `query` PHẢI là URL đầy đủ (vd https://example.com), "
                  "KHÔNG phải câu hỏi. Read-only, không ghi.",
}


def _as_lc_tools(tools_map: dict[str, Callable[[dict], Any]]) -> list:
    """Wrap read callables as LangChain tools the react agent can invoke.

    Each tool takes a single free-form `query` string (the model's ask); the underlying read
    callable receives it as `{"query": ...}`. A permissive one-string schema avoids brittle
    per-tool arg models. Per-tool descriptions (`_TOOL_DESCRIPTIONS`) tell the model what to put
    in `query` — critical for web.scrape, which needs a URL rather than a question.
    """
    from langchain_core.tools import tool as lc_tool

    from my_crew.runtime_backends.read_only_toolset import tool_error_guard

    lc_tools = []
    for name, fn in tools_map.items():
        desc = _TOOL_DESCRIPTIONS.get(name, "Read-only tool. Returns internal data; cannot write.")

        def _make(f, tool_name, description):
            # Guard here too: build_read_toolset already guards its own tools, but a
            # hand-built tools_map (tests, future tiers) must not be able to kill the
            # graph with a raising tool body. Double-guarding is a no-op.
            safe = tool_error_guard(tool_name, f)

            @lc_tool(tool_name.replace(".", "_"), description=description)
            def _call(query: str = "") -> str:
                return str(safe({"query": query}))
            return _call

        lc_tools.append(_make(fn, name, desc))
    return lc_tools


def run_react_work(
    *, title: str, handoff: str, context, settings, tools_map, max_steps: int,
    telemetry=None,
) -> tuple[str, float | None]:
    """Run one team-step's work as a capped tool-calling loop. Returns (text, cost_usd).

    `telemetry` (optional StepTelemetry) receives the summed token counts + cost provenance
    for this attempt; cost itself still returns on the tuple. Absent collector = no-op, so
    the contract and behavior are byte-identical for callers that do not wire it.
    """
    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    from my_crew.config.settings import OPENROUTER_BASE_URL
    from my_crew.llm.team_task_prompt import build_team_step_messages
    from my_crew.runtime_backends.community_loop_core import invoke_capped, record_loop_result

    # Reuse the native system+user prompt so persona/skills/company-docs/red-lines are identical;
    # we only change HOW the model produces text (loop vs one-shot), not WHAT it is told.
    msgs = build_team_step_messages(
        step_title=title, handoff_context=handoff,
        persona=getattr(context, "persona", ""), project=getattr(context, "project", ""),
        memory=getattr(context, "memory", ""), capability=getattr(context, "capability", ""),
    )
    system = next((m["content"] for m in msgs if m["role"] == "system"), "")
    # v45: give this tier an in-STATE file scratch (no Docker, no host, no shell) so a no-shell
    # step routed here can do the compose-early report discipline. The clause + read-back mirror
    # the deep_agent path but the files live in graph state, never a container.
    system = system + _STATE_SCRATCH_CONTRACT
    user = next((m["content"] for m in msgs if m["role"] == "user"), title)

    # LangChain chat model pointed at OpenRouter (same base URL/model as LlmClient). Only used
    # by the react loop; the native path keeps the raw OpenAI SDK client unchanged.
    model = ChatOpenAI(
        model=settings.openrouter_model,
        api_key=settings.openrouter_api_key,
        base_url=OPENROUTER_BASE_URL,
    )
    # Community-standard tool-calling agent (langchain 1.x). System prompt goes ONLY via the
    # SystemMessage below — no `system_prompt=` kwarg — so the tier owns its prompt wiring.
    # v45: attach the StateBackend file-scratch middleware (execute stripped — this tier has NO
    # shell). The read toolset stays the positive read-allowlist; the scratch tools are a SEPARATE,
    # host-free surface (files in graph state), asserted shell-free before binding.
    scratch_mw = _state_scratch_middleware()
    agent = create_agent(model, _as_lc_tools(tools_map), middleware=[scratch_mw])
    result = invoke_capped(
        agent,
        [SystemMessage(content=system), HumanMessage(content=user)],
        recursion_limit=max_steps * 2,  # super-steps ≈ 2× tool rounds (measured: parity)
    )
    text, cost = record_loop_result(
        result, model_name=settings.openrouter_model, telemetry=telemetry
    )
    # v45: surface any scratch report file the agent wrote (compose-early) into the reply, so a
    # no-shell step's report isn't lost in graph state. Best-effort; state files, no teardown race.
    text = _merge_state_scratch_artifacts(result, text)
    return text, cost


#: v45: appended to the create_agent system prompt — the in-state scratch equivalent of the
#: deep_agent compose-early contract, but writing to state files (no /work, no container).
_STATE_SCRATCH_CONTRACT = (
    "\n\nGHI CHÚ CÔNG CỤ: bạn có công cụ ghi/đọc file tạm (write_file/read_file/ls/glob/grep) — "
    "file chỉ nằm trong bộ nhớ phiên làm việc, KHÔNG có shell/thực thi. Với việc viết báo cáo, "
    "hãy ghi bản nháp ra một file .md SỚM rồi tinh chỉnh; kết quả cuối vẫn trả về dưới dạng text."
)

#: Cap on scratch-file text merged into the reply (bound the delivered/audited result).
_SCRATCH_MERGE_MAX_CHARS = 256_000


def _state_scratch_middleware():
    """Build the StateBackend file-scratch middleware with the `execute` tool STRIPPED.

    StateBackend stores files in graph state (ephemeral) — no host FS, no subprocess, no Docker,
    and it is NOT a SandboxBackendProtocol so its `execute` tool cannot run a real shell. We drop
    the `execute` tool anyway so the create_agent tier exposes NO shell-shaped tool at all (moat +
    audit clarity: the tools-tier is provably shell-free). Fail-loud if `execute` somehow can't be
    removed rather than silently binding a shell-named tool.
    """
    from deepagents.backends.state import StateBackend
    from deepagents.middleware.filesystem import FilesystemMiddleware

    mw = FilesystemMiddleware(backend=StateBackend())
    mw.tools = [t for t in mw.tools if getattr(t, "name", "") != "execute"]
    names = [getattr(t, "name", "") for t in mw.tools]
    if "execute" in names:  # defense-in-depth: never bind a shell-shaped tool on this tier
        raise RuntimeError("create_agent scratch: failed to strip `execute` tool (moat guard)")
    return mw


def _merge_state_scratch_artifacts(result: dict, text: str) -> str:
    """Append any `.md` scratch file the agent wrote (in graph state) to `text`, skipping content
    already in the reply. Best-effort: the file surface lives in the returned state under the
    filesystem key; any failure leaves `text` unchanged (the reply is the primary result)."""
    try:
        files = _scratch_files_from_state(result)
        if not files:
            return text
        pieces: list[str] = []
        budget = _SCRATCH_MERGE_MAX_CHARS - len(text)
        for name, content in files.items():
            if budget <= 0:
                break
            if not name.endswith(".md") or not isinstance(content, str) or not content.strip():
                continue
            if content.strip()[:200] in text:  # already substantially in the reply
                continue
            header = f"\n\n### Artifact: {name}\n"
            block = header + content[: max(0, budget - len(header))]
            pieces.append(block)
            budget -= len(block)
        return text + "".join(pieces) if pieces else text
    except Exception:  # noqa: BLE001 — read-back is a supplement; never fail the step
        logger.warning("create_agent scratch read-back failed (ignored)", exc_info=True)
        return text


def _scratch_files_from_state(result: dict) -> dict[str, str]:
    """Extract {name: text} of StateBackend files from the agent's returned state. deepagents stores
    them under a filesystem state key; tolerate shape variance (dict of name→content, or name→obj
    with a `content`/text). Returns {} on any unexpected shape."""
    if not isinstance(result, dict):
        return {}
    # deepagents' StateBackend keeps files under a state key (commonly "files"); probe known keys.
    for key in ("files", "filesystem"):
        raw = result.get(key)
        if isinstance(raw, dict) and raw:
            out: dict[str, str] = {}
            for name, val in raw.items():
                if isinstance(val, str):
                    out[str(name)] = val
                elif isinstance(val, dict):
                    c = val.get("content") or val.get("text")
                    if isinstance(c, str):
                        out[str(name)] = c
            if out:
                return out
    return {}
