"""The thin self-owned tool loop — flat model↔tool rounds over the OpenAI-compatible wire.

Replaces the LangChain `create_agent` react tier with ~150 lines we fully control, mimicking
what the Pi and DeepSeek harnesses converged on independently:

- typed snake_case tool schemas the model was RL-trained against (`typed_tool_specs`);
- salvage → repair → coerce argument pipeline; errors are TOOL RESULTS with actionable
  text, never exceptions (`tool_call_validation`);
- wire rules for DeepSeek-class models (W1-W6, probed live against OpenRouter 2026-08-18):
  assistant `content` is `""` never null on passback, `reasoning`/`reasoning_details`
  passed back verbatim ONLY on tool-call turns, empty tool results become `(no output)`;
- guards: `finish_reason == "length"` fails the whole batch unexecuted with an instructive
  result; an identical consecutive batch is not re-executed;
- when the round budget runs out, ONE tool-free synthesis turn (same contract as
  `community_loop_core._synthesize_from_partial`) — never an empty result.

Contract: `run_thin_loop(...) -> (text, cost_usd)` — identical to `run_react_work`, so
`ToolCallingRuntime` can swap engines behind a config flag. Cost is EXACT (OpenRouter
usage extras via `LlmClient`), not price-table estimated.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from my_crew.runtime_backends.loop_cost_guard import over_cost_cap, with_cost_cap_gap_note
from my_crew.runtime_backends.tool_call_context import tool_call_iteration
from my_crew.runtime_backends.tool_call_validation import prepare_tool_arguments
from my_crew.runtime_backends.typed_tool_specs import ToolSpec, build_typed_specs

logger = logging.getLogger(__name__)

#: Mirror of the recursion-cap synthesis instruction in `community_loop_core` — the model
#: must compose from what it already fetched, say what is MISSING, and never invent data.
_SYNTHESIS_INSTRUCTION = (
    "Hết lượt gọi công cụ. DỪNG gọi tool. Dựa trên TẤT CẢ kết quả công cụ đã có ở trên, "
    "tổng hợp NGAY câu trả lời cuối cùng. Phần nào chưa đủ dữ liệu thì ghi rõ THIẾU và "
    "đã thử tra cứu gì, TUYỆT ĐỐI không bịa số liệu."
)

_TRUNCATED_BATCH_MSG = (
    "Phản hồi của bạn bị cắt giữa chừng (quá dài) nên KHÔNG lệnh gọi công cụ nào được "
    "thực thi. Gọi lại với ÍT lệnh hơn hoặc tham số ngắn hơn."
)

_REPEAT_BATCH_MSG = (
    "Bạn vừa gọi lại Y HỆT loạt công cụ của lượt trước — kết quả sẽ không đổi nên không "
    "chạy lại. Đổi từ khoá/tham số, dùng công cụ khác, hoặc tổng hợp từ dữ liệu đã có."
)


def run_thin_loop(
    *, title: str, handoff: str, context, settings, tools_map, max_steps: int,
    telemetry=None, llm=None, cost_cap_usd: float | None = None,
) -> tuple[str, float | None]:
    """Run one team-step's work as a flat tool loop. Returns (text, cost_usd).

    `llm` is injectable for tests; default builds an `LlmClient(settings)`. `telemetry`
    (optional StepTelemetry) receives summed token counts with cost_source "exact".

    `cost_cap_usd` is this step's own spend ceiling (`RuntimeCaps.cost_cap_usd`). None —
    the default for every tier — leaves the loop bounded only by `max_steps`, exactly as
    before. See `loop_cost_guard` for why enforcement lives in this loop alone.
    """
    from my_crew.llm.team_task_prompt import build_team_step_messages

    if llm is None:
        from my_crew.llm.client import LlmClient

        llm = LlmClient(settings)

    specs = build_typed_specs(tools_map)
    by_name: dict[str, ToolSpec] = {s.name: s for s in specs}
    wire_tools = [s.as_openai_tool() for s in specs]

    base = build_team_step_messages(
        step_title=title, handoff_context=handoff,
        persona=getattr(context, "persona", ""), project=getattr(context, "project", ""),
        memory=getattr(context, "memory", ""), capability=getattr(context, "capability", ""),
    )
    system = next((m["content"] for m in base if m["role"] == "system"), "")
    system += _loop_contract(specs)
    user = next((m["content"] for m in base if m["role"] == "user"), title)
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    in_tok = out_tok = 0
    costs: list[float] = []
    have_cost = False
    prev_batch_key: str | None = None

    def _account(result) -> None:
        nonlocal in_tok, out_tok, have_cost
        in_tok += result.prompt_tokens
        out_tok += result.completion_tokens
        if result.cost_usd is not None:
            costs.append(result.cost_usd)
            have_cost = True

    text: str | None = None
    capped_at_round: int | None = None
    for _round in range(max_steps):
        # The spend ceiling is consulted BEFORE the call, not after: a check that runs
        # afterwards has already paid for the round it was meant to prevent. `cost_cap_usd`
        # is None on every tier by default, so this is a no-op unless a profile sets one.
        if over_cost_cap(costs, cost_cap_usd):
            capped_at_round = _round
            break
        exchange = llm.complete_with_tools(messages, wire_tools)
        _account(exchange.result)
        msg = exchange.message
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            # Final turn — even a "length"-truncated text is the best result we hold.
            text = str(msg.get("content") or "")
            # This turn was paid for before its cost could be counted, so the ceiling has
            # to be re-asked here rather than only at the top of the next round: a model
            # that stops on its own takes this exit and never reaches that check. Measured
            # live — three tool rounds put a step ~3x over its cap, the model then answered
            # without tools, and the step was stored `done` at 15x the cap with no note.
            # The overspend cannot be undone at this point; what it must not do is pass
            # itself off as complete work to `self_check` and the reviewer.
            if over_cost_cap(costs, cost_cap_usd):
                capped_at_round = _round
            break

        messages.append(_assistant_passback(msg, tool_calls))

        if exchange.finish_reason == "length":
            # The batch may itself be truncated mid-JSON — executing it would run
            # half-formed calls. Fail the WHOLE batch with one instructive result each.
            messages.extend(_batch_results(tool_calls, _TRUNCATED_BATCH_MSG))
            prev_batch_key = None
            continue

        batch_key = _batch_signature(tool_calls)
        if batch_key == prev_batch_key:
            messages.extend(_batch_results(tool_calls, _REPEAT_BATCH_MSG))
            continue
        prev_batch_key = batch_key

        # The round number reaches the tool audit only through the ambient context: the
        # toolset was bound before this loop started, so there is no argument to add it to.
        with tool_call_iteration(_round):
            for seq, call in enumerate(tool_calls):
                messages.append(_execute_call(call, by_name, tools_map, seq))

    if text is None and capped_at_round is None:
        # Round budget exhausted while the model still wanted tools: one tool-free
        # synthesis turn over everything fetched so far — never an empty result.
        result = llm.complete(
            messages + [{"role": "user", "content": _SYNTHESIS_INSTRUCTION}]
        )
        _account(result)
        text = result.content

    if capped_at_round is not None:
        # Stopped on cost, so the salvage synthesis above is deliberately skipped: it is
        # another paid call, and spending past the ceiling to explain that the ceiling was
        # reached defeats the guard. Recover the text the same way that synthesis exists to
        # avoid losing it — from the transcript already in hand — and say plainly that the
        # result is partial.
        #
        # `text` when the model ended the loop itself: that turn was never appended to
        # `messages` (only tool-calling turns are passed back), so recovering from the
        # transcript would drop the very answer this exit produced and replace it with the
        # previous round's prose. Prefer what is already in hand.
        text = with_cost_cap_gap_note(
            text if text else _last_assistant_text(messages),
            costs, cost_cap_usd, capped_at_round,
        )

    if telemetry is not None:
        telemetry.record(
            input_tokens=in_tok, output_tokens=out_tok,
            cost_source="exact" if have_cost else None,
        )
    return text, (sum(costs) if have_cost else None)


def _loop_contract(specs: list[ToolSpec]) -> str:
    """The behavior contract appended to the system prompt — proportional to the ACTIVE
    toolset. Tool names/descriptions already travel in the `tools=` wire schema, so the
    prompt only teaches the loop discipline and the source-quality bar."""
    if not specs:
        return ""
    names = ", ".join(s.name for s in specs)
    contract = (
        "\n\nCÔNG CỤ BẠN ĐANG CÓ (gọi trực tiếp, KHÔNG cần xin phép ai): " + names + ". "
        "Bạn làm việc theo VÒNG LẶP: gọi công cụ → đọc kết quả → gọi tiếp nếu chưa đủ, "
        "cho đến khi đủ dữ liệu rồi mới trả lời. TUYỆT ĐỐI không hỏi xin phép tra cứu và "
        "không đề nghị người khác tra hộ — cứ gọi công cụ. Nếu đã thử nhiều từ khoá mà vẫn "
        "không có dữ liệu, hãy nói rõ đã thử gì và thiếu gì, KHÔNG bịa số liệu."
    )
    if any(s.name.startswith("web_") for s in specs):
        contract += (
            " CHUẨN NGUỒN khi tra cứu: ưu tiên trang CHÍNH THỨC của chính đối tượng "
            "(trang chủ, trang giá, thông cáo của dịch vụ/công ty đó) trước nguồn thứ "
            "cấp như đại lý, báo, blog; với mỗi số liệu ghi rõ domain nguồn và ngày "
            "truy cập ngay bên cạnh. Nguồn thứ cấp chỉ dùng khi trang chính thức không "
            "có, và phải ghi chú rõ đó là nguồn thứ cấp."
        )
    return contract


def _last_assistant_text(messages: list[dict]) -> str:
    """The most recent assistant prose in the transcript, for the cost-capped exit.

    Assistant turns that carry tool calls have `content == ""` by wire rule W1, so most of
    a capped loop's transcript holds no prose at all. Walking backwards finds the last turn
    that actually said something; when the model only ever called tools (the common shape
    for a loop cut off early) there is nothing to recover and the caller's gap note stands
    alone. Tool RESULTS are deliberately not harvested here: pasting raw fetched payloads
    into a step's answer would read as the agent's own findings, which is the fabrication
    risk the loop contract exists to prevent.
    """
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = str(msg.get("content") or "").strip()
        if content:
            return content
    return ""


def _assistant_passback(msg: dict, tool_calls: list[dict]) -> dict:
    """The assistant message we send BACK on the next request (wire rules W1/W2):
    content `""` never null; tool_calls sanitized to the standard shape; provider
    reasoning fields passed through verbatim (tool-call turns only — final turns are
    never passed back by construction)."""
    out: dict = {
        "role": "assistant",
        "content": msg.get("content") or "",
        "tool_calls": [
            {
                "id": tc.get("id"),
                "type": "function",
                "function": {
                    "name": (tc.get("function") or {}).get("name"),
                    "arguments": (tc.get("function") or {}).get("arguments") or "{}",
                },
            }
            for tc in tool_calls
        ],
    }
    for key in ("reasoning", "reasoning_details"):
        if msg.get(key):
            out[key] = msg[key]
    return out


def _tool_result(call: dict, content: str) -> dict:
    return {
        "role": "tool",
        "tool_call_id": call.get("id"),
        "content": content.strip() or "(no output)",  # W3
    }


def _batch_results(tool_calls: list[dict], message: str) -> list[dict]:
    """One shared instructive result per call of a REFUSED batch (length/repeat guard).

    Records the round's `tool_call`/`tool_result` events like an executed round would:
    a guarded-off batch is a tool-call error by definition — exactly the signal the
    A/B bench counts — so it must not be invisible in the transcript.
    """
    from my_crew.runtime.step_recorder import head, record_event

    results = []
    for call in tool_calls:
        fn = call.get("function") or {}
        name = str(fn.get("name") or "")
        record_event({"t": "tool_call", "name": name,
                      "args_head": head(fn.get("arguments") or "{}")})
        result = _tool_result(call, message)
        record_event({"t": "tool_result", "name": name,
                      "content_head": head(result["content"])})
        results.append(result)
    return results


def _batch_signature(tool_calls: list[dict]) -> str:
    """Canonical identity of a batch: names + deep-sorted args, ids ignored — so an
    identical retry is recognized even though the provider mints fresh call ids."""
    parts = []
    for tc in tool_calls:
        fn = tc.get("function") or {}
        try:
            args = json.dumps(json.loads(fn.get("arguments") or "{}"), sort_keys=True)
        except (ValueError, TypeError):
            args = str(fn.get("arguments"))
        parts.append(f"{fn.get('name')}({args})")
    return "|".join(parts)


def _execute_call(
    call: dict,
    by_name: dict[str, ToolSpec],
    tools_map: dict[str, Callable[[dict], Any]],
    seq: int = 0,
) -> dict:
    """Validate + run ONE tool call; ANY failure becomes an instructive tool result.

    Records `tool_call`/`tool_result` transcript events (no-op outside a step) — the
    same observability contract the community loop keeps, so peer-review evidence and
    the bench error-rate counter see thin-loop steps identically. Error results are
    recorded too: an invented-tool or bad-args round IS the signal the A/B measures.

    `seq` distinguishes several calls to the same tool within one round, so their stashed
    artifacts do not overwrite each other.
    """
    from my_crew.runtime.step_recorder import head, record_event
    from my_crew.runtime.tool_result_stash import stash_if_oversized
    from my_crew.runtime_backends.read_only_toolset import tool_error_guard

    fn = call.get("function") or {}
    name = str(fn.get("name") or "")
    record_event({"t": "tool_call", "name": name,
                  "args_head": head(fn.get("arguments") or "{}")})

    def _done(content: str) -> dict:
        result = _tool_result(call, content)
        record_event({"t": "tool_result", "name": name,
                      "content_head": head(result["content"])})
        return result

    spec = by_name.get(name)
    if spec is None:
        offered = ", ".join(sorted(by_name))
        return _done(f"Tool {name!r} không tồn tại. Công cụ có: {offered}.")
    args, error, notes = prepare_tool_arguments(spec, fn.get("arguments"))
    if error is not None:
        return _done(error)
    # Double-guard like the react tier: build_read_toolset already guards its callables,
    # but a hand-built tools_map must not be able to kill the loop with a raising body.
    safe = tool_error_guard(spec.legacy_name, tools_map[spec.legacy_name])
    # Stash BEFORE the notes are appended: the notes are the loop's own corrective words
    # (a coerced argument, a dropped field) and must reach the model whole, never end up
    # on the far side of a preview cut.
    content = stash_if_oversized(str(safe(args)), name, seq)
    if notes:
        content = (content.strip() or "(no output)") + "\n" + "\n".join(notes)
    return _done(content)
