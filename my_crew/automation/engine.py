"""Workflow interpreter (v2 M3-P12 D3) — chain READS, PROPOSE writes via the gateway.

`run_workflow` walks a parsed `Workflow`: evaluates the single `when` gate, runs each
`read`/`analyze` step (binding results into a flat context), and for each `propose` step
builds the action dict and ENQUEUES it through `ActionGateway.execute()` (Lớp B ⇒
`pending_approval`). It NEVER auto-executes a write — no `execute_approved`/`approve`, no
direct write-handler call. This holds in BOTH trust modes (v30): the gateway's
propose-only carve-out keeps a handler-less call queuing even when autonomous.

All collaborators are INJECTED (read tools, analyze fn, gateway) so the engine is fully
offline-testable. This module imports `ActionGateway` for the TYPE only; the instance is
passed in. It imports NO `*_write` module and NO `call_tool`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from my_crew.automation.prompts import named_prompt
from my_crew.automation.propose import build_propose_action
from my_crew.automation.schema import AnalyzeStep, ProposeStep, ReadStep, Workflow

if TYPE_CHECKING:
    from my_crew.actions.action_gateway import ActionGateway

# A read tool: called with the step args, returns any result bound into the context.
ReadTool = Callable[[dict[str, Any]], Any]
# An analyze fn: (prompt_text, vars) -> a string summary (the LLM call, injectable).
AnalyzeFn = Callable[[str, dict[str, Any]], str]


@dataclass(frozen=True)
class StepResult:
    """One step's outcome for printing. `proposed` carries the built action (dry-run too)."""

    kind: str  # "read" | "analyze" | "propose" | "skipped"
    detail: str
    proposed: dict | None = None
    status: str | None = None  # gateway status for a real propose (e.g. pending_approval)
    approval_id: int | None = None


def _condition_met(workflow: Workflow, context: dict[str, Any]) -> bool:
    if workflow.when is None:
        return True
    actual = context.get(workflow.when.field)
    return str(actual) == workflow.when.value


def run_workflow(
    workflow: Workflow,
    *,
    context: dict[str, Any] | None = None,
    read_tools: dict[str, ReadTool],
    analyze_fn: AnalyzeFn,
    gateway: ActionGateway,
    rationale: str = "",
    dry_run: bool = False,
) -> list[StepResult]:
    """Run a workflow. `propose` enqueues Lớp B (real) or is printed-only (dry-run).

    Returns a StepResult per step. A propose NEVER executes a write: real mode calls
    `gateway.execute()` (⇒ pending_approval); dry-run builds the same dict but never calls
    the gateway, so the ApprovalStore stays untouched.
    """
    ctx: dict[str, Any] = dict(context or {})
    results: list[StepResult] = []

    if not _condition_met(workflow, ctx):
        cond = workflow.when
        return [StepResult("skipped", f"when not met ({cond.field} != {cond.value})")]

    for step in workflow.steps:
        if isinstance(step, ReadStep):
            tool = read_tools.get(step.tool)
            if tool is None:
                raise ValueError(f"no read tool wired for {step.tool!r}")
            ctx[step.bind] = tool(step.args)
            results.append(StepResult("read", f"{step.tool} -> {step.bind}"))
        elif isinstance(step, AnalyzeStep):
            prompt_text = named_prompt(step.prompt)
            variables = {name: ctx.get(name) for name in step.using}
            ctx[step.bind] = analyze_fn(prompt_text, variables)
            results.append(StepResult("analyze", f"{step.prompt} -> {step.bind}"))
        elif isinstance(step, ProposeStep):
            action = build_propose_action(step.target, step.args, ctx)
            if dry_run:
                results.append(
                    StepResult("propose", f"[dry-run] {step.target}", proposed=action)
                )
            else:
                # NO handler is passed: the gateway can ENQUEUE (Lớp B ⇒ pending_approval)
                # or no-op (skipped — non-Lớp-B with no handler), but it can NEVER execute a
                # write from here. This is the structural guarantee that a workflow proposes,
                # never auto-acts. A destructive/secret action still hits Lớp A hard-deny.
                result = gateway.execute(action, rationale=rationale or workflow.name)
                results.append(
                    StepResult(
                        "propose",
                        f"{step.target} -> {result.status}",
                        proposed=action,
                        status=result.status,
                        approval_id=result.approval_id,
                    )
                )
        else:  # pragma: no cover — parser guarantees only the 3 known step types
            raise ValueError(f"unknown step type: {type(step).__name__}")
    return results
