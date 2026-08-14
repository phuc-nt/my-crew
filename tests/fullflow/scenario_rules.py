"""Reusable LLM scripts for full-flow scenarios — the "user thật" building blocks.

Each helper returns `LlmRule`s for one hop of the pipeline, written against the
REAL prompt contracts:
  * ops intent  — `_INTENT_SYSTEM` marker "DANH SÁCH LỆNH", JSON intent
  * decompose   — team-decompose prompt marker "danh sách nhân sự", DecomposedTask JSON
  * step work   — `role="content"` keyed on the step title in the prompt
  * self-check  — `role="review"` whose prompt asks for a "confidence" field
  * peer review — remaining `role="review"` calls, `{passed, failures}` verdict

Order matters when a scenario combines them: put the most specific rules first
(ScriptedLlm picks the first match).
"""

from __future__ import annotations

import json
from typing import Any

from .scripted_llm import LlmRule


def intent_assign_team_task() -> LlmRule:
    """Classify any CEO ops message as `assign_team_task`, echoing the message
    itself as the `brief` slot — what the real classifier does for task-giving
    messages."""

    def _respond(prompt: str) -> str:
        brief = prompt.rsplit("TIN NHẮN:", 1)[-1].strip()
        return json.dumps(
            {"intent": "command", "command_id": "assign_team_task",
             "slots": {"brief": brief}},
            ensure_ascii=False,
        )

    return LlmRule(role="plan", marker="DANH SÁCH LỆNH", respond=_respond)


def decompose(steps: list[dict[str, Any]], *, title: str,
              pic_id: str | None = None) -> LlmRule:
    """A fixed DAG proposal for the decompose call (validated by the REAL
    `parse_decomposed_task` — invalid steps fail the scenario loudly).
    `pic_id` defaults to the LAST step's assignee — the validator requires the
    terminal (chốt) step to be owned by the PIC.

    Keyed on the decompose system prompt's OWN opening ("bộ phân rã công việc"), not
    on the roster label — several other `role="plan"` prompts (pre-work consult
    propose, sprint intake) render the same "danh sách nhân sự" block, and matching
    on it fed decompose JSON to those calls instead."""
    payload = json.dumps(
        {"title": title, "steps": steps,
         "pic_id": pic_id or steps[-1]["assigned_to"]},
        ensure_ascii=False,
    )
    return LlmRule(role="plan", marker="bộ phân rã công việc", respond=payload)


def propose_ask_ceo(question: str, options: list[str] | None = None,
                    *, once: bool = False) -> LlmRule:
    """The pre-work propose call decides to ask the CEO (`agent_id: "ceo"`), which is
    the ONLY path that mints a clarification. Shares `role="plan"` with decompose, so
    it is keyed on the propose prompt's own header — place BEFORE `decompose()`."""
    payload = json.dumps(
        {"consults": [{"agent_id": "ceo", "question": question,
                       "options": options or []}], "split": []},
        ensure_ascii=False,
    )
    return LlmRule(role="plan", marker="Đồng nghiệp có thể hỏi",
                   respond=payload, once=once)


def propose_no_consult() -> LlmRule:
    """No consult, no split — what the propose call returns for a self-contained step.
    Place AFTER any `propose_ask_ceo(once=True)` so the one-shot ask wins first."""
    return LlmRule(role="plan", marker="Đồng nghiệp có thể hỏi",
                   respond='{"consults":[],"split":[]}')


def sprint_intake(goal: str, *, assigned_to: str, acceptance: str = "- kết quả đủ ý",
                  needs_web: bool = False) -> LlmRule:
    """The sprint intake call — one person does the whole thing, no decomposition.
    Keyed on the intake system prompt's own opening ("bộ tiếp nhận việc").
    Fail-open by design in product code: a broken intake still yields a minimal plan
    from the CEO's own brief, so a missing rule here degrades silently rather than
    failing loudly — script it explicitly whenever a scenario routes to sprint."""
    payload = json.dumps(
        {"goal": goal, "acceptance": acceptance,
         "assigned_to": assigned_to, "needs_web": needs_web},
        ensure_ascii=False,
    )
    return LlmRule(role="plan", marker="bộ tiếp nhận việc", respond=payload)


def step_work(title_marker: str, result_text: str, *, once: bool = False) -> LlmRule:
    """The content completion for one step, matched on its title in the prompt."""
    return LlmRule(role="content", marker=title_marker, respond=result_text, once=once)


def self_check_pass() -> LlmRule:
    """Always-green self-check. The self-check prompt is the only review-role
    prompt that asks for a `confidence` field — that is the routing marker."""
    verdict = json.dumps(
        {"passed": True, "failures": [], "confidence": 0.9, "criteria": []}
    )
    return LlmRule(role="review", marker='"confidence"', respond=verdict)


def peer_review(passed: bool, failures: list[str] | None = None,
                *, once: bool = False) -> LlmRule:
    """A peer-review verdict for the review step's structured call. Matched on
    the shared rubric header both review prompts carry — place AFTER
    `self_check_pass()` so the confidence marker wins for self-checks."""
    verdict = json.dumps(
        {"passed": passed, "failures": failures or [], "notes": []},
        ensure_ascii=False,
    )
    return LlmRule(role="review", marker="", respond=verdict, once=once)


def utility_rules() -> list[LlmRule]:
    """Post-delivery housekeeping calls (`role="util"`): task reflection answers
    its own "nothing to learn" token; every other util call (memory-fact
    extraction, digests) gets an empty string — the documented "nothing" shape."""
    return [
        LlmRule(role="util", marker="KHONG_CO_GI", respond="KHONG_CO_GI"),
        LlmRule(role="util", marker="", respond=""),
    ]


def catch_all_content(text: str = "Nội dung phụ trợ.") -> LlmRule:
    """Fallback for auxiliary content calls a scenario does not care about
    (delivery summaries, room messages). Keep LAST in the rule list."""
    return LlmRule(role="content", marker="", respond=text)
