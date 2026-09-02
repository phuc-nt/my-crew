"""The crew shapes the router may pick — and the rule that says "none of them".

Context-crew: a crew is worth its coordination cost only when the plan has a boundary
one strong agent cannot cross inside its own context. Each shape is a hypothesis with a
kill criterion fixed before it was measured (`my_crew/bench/hypothesis_stats.py`). Two
survived:

  - `do_review`: one agent does, a DIFFERENT agent grades against a fixed rubric.
    Independence of the reviewer is the whole point; the CEO asked for it in the brief.
    Measured: the independent reviewer caught 10/12 seeded errors (H2 kept).
  - `permission_chain`: a step needs a sensitive tool (shell, external write, mailbox)
    and therefore its own permission boundary. Safety, not quality — never benched, never
    removable: the sprint hardcodes shell/write off, so this is the only lane those run in.

One was killed. `fanout` — ≥2 independent lookups in separate contexts, then merged —
claimed breadth one context cannot hold. Blind-judged over 4 cases × 3 runs it beat the
sprint 4/12 times at 1.5× the cost (H1), and the cheap-specialist variant also lost 8/12
at 0.6× the cost (H3): cheaper, but not at equal quality. A plan that looks like a
fan-out therefore has no boundary a sprint lacks and runs as a sprint like any other
chain of same-tool steps. (The coordinator's runtime fan-out — `fanout_insert`, splitting
one entity-listing step inside a crew that already exists — is a different mechanism
and unaffected.)

Any other plan — a chain of same-tool steps, a "team" that is really one person's
work in pieces — has no boundary a sprint lacks, so the router runs it as a sprint.
A CEO-forced `team:` plan that matches none is recorded as `"custom"` rather than
refused: the prefix is the assigning human's decision, the shape is an observation.

Pure functions over the validated `DecomposedTask`; no model call, no store.
"""

from __future__ import annotations

from my_crew.agent.sprint_intake import EXTERNAL_WRITE_REFUSAL
from my_crew.agent.task_decomposition import DecomposedTask, find_terminals

#: A chain whose steps cross a permission boundary (shell / external write / mail).
PERMISSION_CHAIN_SHAPE = "permission_chain"
#: One deliverable plus an independent reader of it (reviewer ≠ author, one rework).
DO_REVIEW_SHAPE = "do_review"

#: The shapes `classify_shape` can return, in precedence order. `route["shape"]` is one
#: of these or `"custom"` (forced/refusal team routes that match none).
CREW_SHAPES = (PERMISSION_CHAIN_SHAPE, DO_REVIEW_SHAPE)

#: Recorded on a team route the router did not get to gate (CEO prefix, safety refusal).
CUSTOM_SHAPE = "custom"

#: A do+review crew is a SMALL plan — the shape exists to buy an independent grader
#: for one deliverable, not to review a long chain. Same bound as the review waiver
#: (`SMALL_TASK_MAX_STEPS`): larger plans already review their terminal under the v64
#: policy, so they do not need this shape to get a second pair of eyes.
DO_REVIEW_MAX_STEPS = 3


def _sensitive(step) -> bool:
    return bool(step.needs_shell or step.external_write or getattr(step, "needs_mail", False))


def classify_shape(task: DecomposedTask, signals: dict[str, int] | None = None) -> str | None:
    """Which crew shape this plan is — or `None` when it is one person's work in pieces.

    `signals` are the brief-level numbers from `route_signals`; only
    `needs_independent_review` is read here (the plan itself cannot say the CEO asked
    for a second reader). Precedence: a sensitive step decides first because it is a
    SAFETY boundary — a plan with a shell step must never be run as a sprint just
    because it is short. Length is deliberately not a
    condition for `permission_chain`: the sprint hardcodes shell/write off, so a long
    plan with one shell step turned into a sprint would silently drop that step.
    """
    steps = task.steps
    if any(_sensitive(s) for s in steps):
        return PERMISSION_CHAIN_SHAPE
    wants_review = bool((signals or {}).get("needs_independent_review"))
    if wants_review and len(steps) <= DO_REVIEW_MAX_STEPS:
        return DO_REVIEW_SHAPE
    return None


def mark_do_review(task: DecomposedTask) -> DecomposedTask:
    """Flag the plan's terminal step(s) for peer review — the "review" half of do+review.

    Runs AFTER `validate_decomposition` (whose `apply_review_policy` waives review on
    small internal plans — exactly the plans this shape is made of), so the flag it sets
    is what gets persisted and what `review_insert` reads at runtime. The reviewer is
    chosen there by `pick_reviewer`, which never returns the author; a one-agent fleet
    yields no reviewer and the runtime skips the review rather than stalling.
    """
    terminal_ids = {s.step_id for s in find_terminals(task.steps)}
    if all(s.needs_review for s in task.steps if s.step_id in terminal_ids):
        return task
    return task.model_copy(update={"steps": tuple(
        s.model_copy(update={"needs_review": True})
        if s.step_id in terminal_ids and not s.needs_review else s
        for s in task.steps
    )})


def enforce_refusal_boundary(task: DecomposedTask, refusal: str) -> DecomposedTask:
    """Make the plan carry the boundary the sprint gate refused the brief for.

    `sprint_refusal` reads the BRIEF ("gửi email cho khách"); the decompose model writes
    the PLAN, and it does forget to flag the sending step. Left alone, that plan has no
    sensitive step, so `classify_shape` sees no permission chain — and the shape gate
    would run it as a sprint, which hardcodes `external_write=False` and so skips the
    mandatory review and the gateway approval the refusal existed to keep. The terminal
    step(s) get the flag: whatever leaves the company leaves at the end of the plan.
    Only the external-write refusal has a step flag to restore; a shell refusal has no
    way to know WHICH step runs code, and the multi-staff/long-horizon ones name no tool.
    """
    if not refusal.startswith(EXTERNAL_WRITE_REFUSAL):
        return task
    if any(s.external_write for s in task.steps):
        return task
    terminal_ids = {s.step_id for s in find_terminals(task.steps)}
    return task.model_copy(update={"steps": tuple(
        s.model_copy(update={"external_write": True}) if s.step_id in terminal_ids else s
        for s in task.steps
    )})
