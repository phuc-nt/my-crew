"""Per-team-task cost cap enforcement (v12 M28b; DERIVED headroom v13 M34).

`TeamTaskStore.sum_cost` already adds step + decompose + aggregate cost (see its
docstring); this module is the one-line cap comparison the coordinator ticker calls
every tick before acting, so the cap check lives in ONE place rather than being
inlined at each of the ticker's several call sites.

**v13 update — the old v12 overshoot-bound clause below is now FALSE and superseded
by `spawn_headroom_usd`**: v12 said "a step is one bounded LLM call... worst-case
overshoot is bounded by one step's cost". Since M31–M33 a single step's own graph run
may make up to ~8 bounded LLM calls (perceive/work, self_check, ≤2 rework rounds each
re-running self_check, ≤2 consult questions, plus a peer-review step's own verdict
call) — still BOUNDED per step (the ≤2 counters are hard caps in graph state), but no
longer "one call". `check_cost_cap` (the HARD stop, checked once per tick before any
other action) is unaffected by this — it only ever sums cost already RECORDED in the
store, exactly as before.

**Parallel dispatch (v13 M34) — no reservation ledger, DERIVED headroom instead**:
concurrent steps mean more than one step can be in flight against the SAME cap at
once, so a naive "check cap, then spawn" ticker loop could rubber-stamp several steps
whose COMBINED (not yet recorded) cost blows the cap before any of their `mark_done`
writes land. The tempting fix — a reservation/ledger table the ticker writes to before
spawning and reconciles after — was rejected: a reservation has to
be released on EVERY exit path (done, failed, timeout, kill, crash, retry, the task
itself getting `stalled`/`cancelled` mid-flight) or it leaks headroom forever; missing
even one of those paths silently starves the task of spawnable steps. Instead,
`spawn_headroom_usd` DERIVES the in-flight reservation from the steps table itself —
`Σ(estimate over steps status='running')` — which is automatically correct on every
exit path because a step's status transition (to `done`/`failed`/`timeout`, or back to
`pending` via a fresh dead-pid retry reserve) is the SAME write that already has to
happen for that step's lifecycle; there is no separate row to leak or reconcile.
`awaiting_approval` is deliberately NOT counted as "in flight" here (mirrors
`coordinator_graph`'s lease-clock-paused treatment of that status) — a step paused on
a human decision releases its headroom back to the task while it waits, rather than
holding a slot hostage for however long the CEO takes to decide.
"""

from __future__ import annotations

from dataclasses import dataclass

from my_crew.runtime.team_task_store import TeamTask, TeamTaskStore

#: Statuses counted as "in flight" for derived-headroom purposes — deliberately
#: EXCLUDES `awaiting_approval` (paused on a human decision, lease clock stopped,
#: headroom released while it waits) and every terminal status (`done`'s cost is
#: already in `sum_cost`'s actual total; `failed`/`timeout` spent nothing further).
_RUNNING_STATUSES = ("running",)


@dataclass(frozen=True)
class CostCapResult:
    """Whether a team task is still under its cost cap, and the numbers behind it."""

    within_cap: bool
    spent_usd: float
    cap_usd: float


def check_cost_cap(store: TeamTaskStore, task_id: str, *, cap_usd: float) -> CostCapResult:
    """Sum step + decompose + aggregate cost for `task_id` and compare to `cap_usd`.

    `cap_usd` is the caller's resolved `company.yaml::team_task_cap_usd` (default
    $2, v1 has no per-task override) — this function does not read company config
    itself so it stays a pure, easily-tested comparison.
    """
    spent = store.sum_cost(task_id)
    return CostCapResult(within_cap=spent <= cap_usd, spent_usd=spent, cap_usd=cap_usd)


def step_cost_estimate_usd(cap_usd: float, *, max_steps: int) -> float:
    """v1 conservative constant per-step cost estimate for derived-headroom purposes:
    `cap_usd / max_steps` — deliberately NOT a historical average (no such data exists
    yet, and averaging would let a run of cheap steps silently raise the estimate the
    ticker trusts for the NEXT, possibly expensive, step). `max_steps` is the caller's
    resolved `task_decomposition.MAX_STEPS` (confirmed-DAG ceiling) — a task can never
    have more than this many CONFIRMED steps running at once, so dividing the cap by it
    is a deliberately pessimistic per-step share, not a prediction of actual spend.
    """
    if max_steps <= 0:
        return cap_usd
    return cap_usd / max_steps


def spawn_headroom_usd(
    store: TeamTaskStore, task: TeamTask, *, cap_usd: float, step_estimate_usd: float,
) -> float:
    """DERIVED spawn headroom for `task`: `cap_usd − Σ(actual cost of done steps +
    decompose + aggregate) − Σ(step_estimate_usd over steps currently 'running')`.

    No reservation table: the running-steps sum IS the reservation, re-derived fresh
    from `task.steps` on every call — nothing to leak on kill/timeout/crash/retry/pause
    (see module docstring). Callers compare the result against the NEXT candidate
    step's own estimate (`step_estimate_usd`, uniform v1) before spawning it; a
    negative or zero result means "defer this tick, do not spawn" (never "stall the
    task" — that is `check_cost_cap`'s hard-stop job on the ACTUAL recorded total, not
    this soft pre-spawn gate on the projected total).
    """
    spent = store.sum_cost(task.id)
    running_count = sum(1 for s in task.steps if s.status in _RUNNING_STATUSES)
    reserved = running_count * step_estimate_usd
    return cap_usd - spent - reserved


def cost_warn_ratio(cap: CostCapResult, *, warn_ratio: float) -> bool:
    """True iff `cap.spent_usd` has crossed `warn_ratio` of `cap.cap_usd` but is still
    within the cap (M32's 80%-warn — a heads-up BEFORE the hard `within_cap=False`
    stop, never a substitute for it). `cap_usd <= 0` (a misconfigured/zero cap) never
    warns — division by zero would otherwise make every task warn immediately, which is
    a worse signal than no warning at all for a cap that is not meaningfully set."""
    if cap.cap_usd <= 0 or not cap.within_cap:
        return False
    return (cap.spent_usd / cap.cap_usd) >= warn_ratio
