"""ScriptedLlm — the ONE LLM double for full-flow scenarios.

Routes each `LlmClient.complete` call to a scenario-provided rule keyed on
(`role=`, prompt marker). First matching rule wins, so order rules from most to
least specific. An unmatched call FAILS LOUD with the role + prompt head — a
scenario must script every hop it exercises; silence would hide a routing bug.

Every call (matched or not) is traced, so the scenario's JSONL shows the exact
sequence of model calls the product code made.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from my_crew.llm.client import LlmResult, ToolExchange
from my_crew.runtime.step_recorder import record_event

#: A rule's `respond` may be a fixed string or a callable receiving the full
#: prompt text (all message contents joined) and returning the completion. For
#: `complete_with_tools` calls it may instead return a list of tool-call dicts
#: (OpenAI wire shape) — the double then answers with a tool-call turn.
Responder = str | list[dict] | Callable[[str], str | list[dict]]


def tool_call(name: str, arguments: str, call_id: str = "call_1") -> dict:
    """One scripted tool call in the OpenAI wire shape (arguments = JSON string)."""
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": arguments}}


@dataclass
class LlmRule:
    """One scripted response: match on role (None = any) + substring marker."""

    marker: str
    respond: Responder
    role: str | None = None
    #: consume-once rules let a scenario script "fail round 0, pass round 1"
    #: with two rules sharing a marker (first match is popped after use).
    once: bool = False
    hits: int = field(default=0, compare=False)


class ScriptedLlm:
    """Drop-in for the class-level `LlmClient.complete` patch."""

    def __init__(self, rules: list[LlmRule], trace: Callable[..., None]):
        self._rules = list(rules)
        self._trace = trace
        self.calls: list[dict[str, Any]] = []

    def add_rules(self, *rules: LlmRule) -> None:
        self._rules.extend(rules)

    def complete(
        self, messages: list[dict[str, str]], *, model: str | None = None,
        role: str | None = None,
    ) -> LlmResult:
        text = "\n".join(str(m.get("content", "")) for m in messages)
        # The double honors the seam's v80 contract: the real `complete` records
        # llm_request/llm_response into the step transcript, so full-flow scenarios
        # must see the same transcript a real run produces (no-op outside a step).
        record_event({"t": "llm_request", "role": role, "chain": ["scripted"],
                      "messages": messages})
        for i, rule in enumerate(self._rules):
            if rule.role is not None and rule.role != role:
                continue
            if rule.marker not in text:
                continue
            rule.hits += 1
            content = rule.respond(text) if callable(rule.respond) else rule.respond
            if rule.once:
                self._rules.pop(i)
            record = {
                "role": role, "marker": rule.marker,
                "prompt_head": text[:200], "response_head": content[:200],
            }
            self.calls.append(record)
            self._trace("llm", **record)
            record_event({"t": "llm_response", "model": "scripted", "content": content,
                          "prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 0.0,
                          "fallback_from": []})
            return LlmResult(
                content=content, model="scripted", prompt_tokens=1,
                completion_tokens=1, cost_usd=0.0,
            )
        self._trace("llm_unmatched", role=role, prompt_head=text[:400])
        raise AssertionError(
            f"ScriptedLlm: no rule for role={role!r}.\nPrompt head:\n{text[:600]}"
        )

    def complete_with_tools(
        self, messages: list[dict], tools: list[dict], *, model: str | None = None,
        role: str | None = None,
    ) -> ToolExchange:
        """Drop-in for the class-level `LlmClient.complete_with_tools` patch (thin loop).

        Same rule routing as `complete`; a rule whose responder yields a LIST answers
        with a tool-call turn (finish_reason "tool_calls"), a string ends the loop as
        the final text turn. Mirrors the real seam's v80 transcript contract
        (llm_request with tool names, llm_response with tool_calls summary).
        """
        text = "\n".join(str(m.get("content", "")) for m in messages)
        record_event({"t": "llm_request", "role": role, "chain": ["scripted"],
                      "tools": [t.get("function", {}).get("name") for t in tools],
                      "messages": messages})
        for i, rule in enumerate(self._rules):
            if rule.role is not None and rule.role != role:
                continue
            if rule.marker not in text:
                continue
            rule.hits += 1
            out = rule.respond(text) if callable(rule.respond) else rule.respond
            if rule.once:
                self._rules.pop(i)
            if isinstance(out, list):
                message: dict = {"role": "assistant", "content": "", "tool_calls": out}
                finish, content = "tool_calls", ""
            else:
                message = {"role": "assistant", "content": out}
                finish, content = "stop", out
            record = {
                "role": role, "marker": rule.marker, "prompt_head": text[:200],
                "response_head": content[:200] or json.dumps(out, ensure_ascii=False)[:200],
            }
            self.calls.append(record)
            self._trace("llm_tools", **record)
            record_event({"t": "llm_response", "model": "scripted", "content": content,
                          "tool_calls": [
                              {"name": (tc.get("function") or {}).get("name"),
                               "arguments": (tc.get("function") or {}).get("arguments")}
                              for tc in (message.get("tool_calls") or [])
                          ],
                          "finish_reason": finish, "prompt_tokens": 1,
                          "completion_tokens": 1, "cost_usd": 0.0, "fallback_from": []})
            return ToolExchange(
                message=message, finish_reason=finish,
                result=LlmResult(content=content, model="scripted", prompt_tokens=1,
                                 completion_tokens=1, cost_usd=0.0),
            )
        self._trace("llm_tools_unmatched", role=role, prompt_head=text[:400])
        raise AssertionError(
            f"ScriptedLlm: no tools rule for role={role!r}.\nPrompt head:\n{text[:600]}"
        )
