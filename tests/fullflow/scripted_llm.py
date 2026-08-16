"""ScriptedLlm — the ONE LLM double for full-flow scenarios.

Routes each `LlmClient.complete` call to a scenario-provided rule keyed on
(`role=`, prompt marker). First matching rule wins, so order rules from most to
least specific. An unmatched call FAILS LOUD with the role + prompt head — a
scenario must script every hop it exercises; silence would hide a routing bug.

Every call (matched or not) is traced, so the scenario's JSONL shows the exact
sequence of model calls the product code made.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from my_crew.llm.client import LlmResult
from my_crew.runtime.step_recorder import record_event

#: A rule's `respond` may be a fixed string or a callable receiving the full
#: prompt text (all message contents joined) and returning the completion.
Responder = str | Callable[[str], str]


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
