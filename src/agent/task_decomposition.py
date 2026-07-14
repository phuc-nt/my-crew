"""Team-task decomposition: schema + deterministic validation (v12 M28b).

One bounded, synchronous LLM call turns a CEO brief into a `DecomposedTask` (a DAG of
at most 7 steps). The LLM only proposes; every hard constraint (step count, DAG
acyclicity, `assigned_to` role authorization) is re-checked here in CODE, not trusted
from the model's output — the same "LLM fills, code validates" split the ops chat-ops
catalog and slot-filling engine already use.

Role authz: `assigned_to` must be a company staff id (an ENABLED registry agent id,
excluding the coordinator itself and the admin agent — see
`team_task_roster.assignable_staff`, the single source of truth both gates below call).
This gate runs twice by design: once here at decompose-validation time (before the CEO
ever sees a preview, via `ops_assign_team_task._staff_roster`), and again at dispatch
time in the coordinator ticker (`coordinator_nodes.tick_actions.reserve_and_spawn`, via
`CoordinatorDeps.roster_ok`, in case the registry/roles changed between confirm and
dispatch) — a step whose assignee is no longer valid must never silently run; the
dispatch-time re-check marks the step `failed` + escalates instead of spawning it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

#: Hard ceiling on a single team task's DAG — keeps a decomposition reviewable in one
#: CEO preview and bounds worst-case fan-out cost.
MAX_STEPS = 7

#: Valid `step_type` values a DECOMPOSE proposal may set. Only "work" is ever proposed
#: by the LLM/CEO-confirmed DAG — "review"/"rework" are minted EXCLUSIVELY by the
#: ticker rule (`coordinator_nodes.tick_actions`) after confirm, never by decompose;
#: still validated here (not just accepted at face value) so a compromised/buggy LLM
#: completion can never smuggle a system-reserved step_type into a CEO-confirmed plan.
_STEP_TYPES = ("work", "review", "rework")


class TeamStepPlan(BaseModel):
    """One proposed DAG step (pre-persistence — the store's own `TeamStep` is the
    persisted shape; this is the LLM-facing/validation-facing shape)."""

    step_id: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=300)
    assigned_to: str = Field(min_length=1, max_length=40)
    deps: tuple[str, ...] = Field(default_factory=tuple)
    # Self-check acceptance criteria (optional, free text) — per-step METADATA, not DAG
    # structure. Deliberately EXCLUDED from `decomposition_content_hash` (see that
    # function's docstring): the hash binds the CEO's confirm to the DAG shape (which
    # steps, who runs them, what depends on what), not to this rubric text, so a task
    # WITH acceptance hashes byte-identical to one without. Round-trips into
    # `team_steps.acceptance` (store) and from there into the self_check node's prompt.
    acceptance: str = Field(default="", max_length=2000)
    # step_type/needs_review (P2 peer review): a decompose proposal must only ever
    # describe CONTENT work — "work" is the only value a real CEO-confirmed DAG should
    # ever carry (see `_validate_step_type_bounds` below); review/rework rows are
    # ticker-minted post-confirm, never part of what the CEO previews/confirms.
    step_type: str = Field(default="work")
    # LLM-settable, code-validated: True for a content step whose completion should
    # trigger the ticker's peer-review insert rule. Defaults False (v12-compatible —
    # a step without this field set never gets a review inserted).
    needs_review: bool = False
    # v45 tier-0 routing: LLM-settable, True ONLY when the step must run real shell/code
    # (pip/curl/execute a script). Default False ⇒ the step runs on the fast, Docker-free
    # create_agent tier; True ⇒ it escalates to the deep_agent Docker sandbox. It IS part of
    # `decomposition_content_hash` (unlike `acceptance`): it selects the RUNTIME + trust
    # boundary the step runs on, so the CEO's confirm must bind it — a task cannot silently
    # change its shell posture post-confirm. Fail-closed: the light tier has no shell, so
    # mis-setting this False only fails a shell task; it can never grant unsafe shell access.
    needs_shell: bool = False

    @field_validator("step_id", "assigned_to")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("step_type")
    @classmethod
    def _valid_step_type(cls, v: str) -> str:
        v = v.strip() or "work"
        if v not in _STEP_TYPES:
            raise ValueError(f"step_type must be one of {_STEP_TYPES}, got {v!r}")
        return v

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be blank")
        return v

    @field_validator("acceptance")
    @classmethod
    def _strip_acceptance(cls, v: str) -> str:
        return v.strip()


class DecomposedTask(BaseModel):
    """The LLM's proposed decomposition of a CEO brief into a step DAG.

    `requires_approval=True` is fixed (v1 decision): a team task's own external writes
    still go through the normal per-agent Lớp B gate — this flag is documentary/forward
    -compatible, not a bypass switch.
    """

    steps: tuple[TeamStepPlan, ...] = Field(min_length=1, max_length=MAX_STEPS)
    requires_approval: bool = True
    # v15 PIC: the staffer responsible for the WHOLE task (chịu trách nhiệm chính).
    # LLM-proposed when the CEO did not @-name one; ALWAYS code-overridden with the
    # CEO's explicit @id when they did (see `validate_decomposition`'s `pic_id` param —
    # the model's value can never silently swap a CEO-named PIC). "" = task has no PIC
    # (every pre-v15 task) — all PIC rules are skipped, byte-compatible behavior.
    # Metadata like `acceptance`: NOT part of `decomposition_content_hash`.
    pic_id: str = ""

    @field_validator("pic_id")
    @classmethod
    def _strip_pic(cls, v: str) -> str:
        return v.strip()

    @field_validator("steps")
    @classmethod
    def _unique_step_ids(cls, steps: tuple[TeamStepPlan, ...]) -> tuple[TeamStepPlan, ...]:
        seen: set[str] = set()
        for s in steps:
            if s.step_id in seen:
                raise ValueError(f"duplicate step_id {s.step_id!r}")
            seen.add(s.step_id)
        return steps

    @model_validator(mode="after")
    def _deps_reference_known_steps(self) -> DecomposedTask:
        ids = {s.step_id for s in self.steps}
        for s in self.steps:
            unknown = [d for d in s.deps if d not in ids]
            if unknown:
                raise ValueError(f"step {s.step_id!r} depends on unknown step(s) {unknown}")
            if s.step_id in s.deps:
                raise ValueError(f"step {s.step_id!r} cannot depend on itself")
        return self

    @model_validator(mode="after")
    def _step_type_bounds(self) -> DecomposedTask:
        """Decompose-time bounds (Decision D's guardrail): a CEO-confirmed DAG must
        only ever propose content ("work") steps — "review"/"rework" are ticker-
        reserved, minted post-confirm only (see `team_task_steps.insert_step`), so
        `needs_review` (only meaningful on a content step — review-of-review would loop
        forever otherwise) is implicitly bounded to "work" steps by the same check."""
        for s in self.steps:
            if s.step_type != "work":
                raise ValueError(
                    f"step {s.step_id!r}: step_type {s.step_type!r} is reserved for "
                    "ticker-inserted rows and cannot appear in a decompose proposal"
                )
        return self


class DecompositionError(ValueError):
    """Raised by `validate_decomposition` — always carries a CEO/operator-facing
    message (no internals leaked), matching `ops_catalog`'s ValueError convention."""


def parse_decomposed_task(raw_json: str) -> DecomposedTask:
    """Parse the LLM's raw JSON completion into a `DecomposedTask`.

    Raises `DecompositionError` on anything that is not valid JSON or does not match
    the schema — the caller (ops_catalog.assign_team_task) retries on this (bounded,
    before the CEO ever sees a preview)."""
    from src.llm.team_task_check_prompt import strip_json_fences

    try:
        doc = json.loads(strip_json_fences(raw_json))
    except json.JSONDecodeError as exc:
        raise DecompositionError(f"phân rã không phải JSON hợp lệ: {exc}") from None
    if not isinstance(doc, dict):
        raise DecompositionError("phân rã phải là một object JSON")
    try:
        return DecomposedTask.model_validate(doc)
    except Exception as exc:  # noqa: BLE001 — pydantic ValidationError, wrapped uniformly
        raise DecompositionError(f"phân rã không hợp lệ: {exc}") from None


def _acyclic(steps: tuple[TeamStepPlan, ...]) -> bool:
    """Kahn's algorithm: True iff the deps graph has no cycle."""
    indeg = {s.step_id: 0 for s in steps}
    adj: dict[str, list[str]] = {s.step_id: [] for s in steps}
    for s in steps:
        for d in s.deps:
            adj[d].append(s.step_id)
            indeg[s.step_id] += 1
    queue = [sid for sid, deg in indeg.items() if deg == 0]
    visited = 0
    while queue:
        node = queue.pop()
        visited += 1
        for nxt in adj[node]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    return visited == len(steps)


def validate_pic_terminal(steps: tuple[TeamStepPlan, ...], pic_id: str) -> None:
    """v15 PIC hard rule (red-team F5), applied to a PENDING slice of steps: the slice
    must have EXACTLY ONE terminal step (no step in the slice depends on it) and that
    step must be assigned to the PIC — the PIC owns the final synthesis/sign-off of
    whatever work remains. One terminal ⇒ every other step in the slice transitively
    feeds it. A 1-step slice ⇒ that step belongs to the PIC.

    "Slice" deliberately: at decompose time the slice is the WHOLE plan (everything is
    pending); at amend time it is the NEW pending steps only — a completed (frozen)
    step has no new dependents by construction (`_AMEND_SYSTEM` forbids referencing
    frozen ids), so including frozen rows would make every amend fail with multiple
    terminals. Blank `pic_id` never reaches here (caller skips — no-PIC task)."""
    dep_targets = {d for s in steps for d in s.deps}
    terminals = [s for s in steps if s.step_id not in dep_targets]
    if len(terminals) != 1:
        ids = ", ".join(s.step_id for s in terminals)
        raise DecompositionError(
            f"kế hoạch phải có ĐÚNG MỘT bước chốt cuối (tổng hợp) — hiện có "
            f"{len(terminals)} bước không ai phụ thuộc: {ids}"
        )
    if terminals[0].assigned_to != pic_id:
        raise DecompositionError(
            f"bước chốt cuối [{terminals[0].step_id}] phải do PIC ({pic_id}) đảm nhận, "
            f"đang giao cho {terminals[0].assigned_to}"
        )


def validate_decomposition(
    task: DecomposedTask, *, staff_ids: Iterable[str], pic_id: str | None = None,
) -> DecomposedTask:
    """Deterministic, code-side gate — bounds + acyclic DAG + role authz (+ PIC, v15).

    `staff_ids`: the set of valid `assigned_to` targets. The codebase has no separate
    "company staff roster" beyond the fleet registry (`company.yaml` carries identity +
    coordinator id + cost cap only, no staff list) — the caller passes
    `{e.id for e in load_registry()}` (optionally filtered to `enabled` entries) as the
    staff set. Documented interpretation, not silently assumed.

    `pic_id` (v15): None → use the LLM's own `task.pic_id` proposal (may be "", i.e.
    no PIC — every pre-v15 caller, byte-compatible). Non-None → the CEO explicitly
    @-named this PIC: it OVERRIDES whatever the model proposed (red-team F4 — a model
    completion can never swap a CEO-named PIC) and must itself be a valid staff id.
    Whenever the effective PIC is non-blank, `validate_pic_terminal` enforces the
    one-terminal-owned-by-PIC rule over the whole (all-pending) plan.

    Raises `DecompositionError` (never lets a bad step through) so the caller can turn
    it into a clean CEO-facing message.
    """
    if not (1 <= len(task.steps) <= MAX_STEPS):
        raise DecompositionError(
            f"số bước phải từ 1 đến {MAX_STEPS} (nhận được {len(task.steps)})"
        )
    if not _acyclic(task.steps):
        raise DecompositionError("kế hoạch có vòng lặp phụ thuộc (dependency cycle)")

    staff = set(staff_ids)
    unauthorized = sorted({s.assigned_to for s in task.steps if s.assigned_to not in staff})
    if unauthorized:
        raise DecompositionError(
            f"các bước được giao cho agent không tồn tại/không hợp lệ: {', '.join(unauthorized)}"
        )

    effective_pic = task.pic_id if pic_id is None else pic_id.strip()
    if pic_id is not None and effective_pic != task.pic_id:
        task = task.model_copy(update={"pic_id": effective_pic})
    if effective_pic:
        if effective_pic not in staff:
            raise DecompositionError(
                f"PIC {effective_pic!r} không có trong danh sách nhân sự có thể giao việc"
            )
        validate_pic_terminal(task.steps, effective_pic)
    return task


def decomposition_content_hash(task: DecomposedTask) -> str:
    """Deterministic content hash of the confirmed DAG (TOCTOU-proof binding, req 4).

    Canonical JSON (sorted keys, stable step order) so the SAME decomposition always
    hashes the same, and any mutation (added/removed/reassigned step) changes the hash
    — confirm re-verifies this hash before dispatch is ever allowed.

    Reads `step_id`/`title`/`assigned_to`/`deps` always, plus `needs_shell` (v45) ONLY on
    steps where it is True — `acceptance` (a per-step self-check rubric) is never included.

    `needs_shell` binds into the hash because it selects a step's RUNTIME + trust boundary
    (create_agent vs the deep_agent Docker sandbox), so the CEO's confirm must cover it.
    But it is emitted CONDITIONALLY (key present only when True) so a DAG with no shell steps
    — every pre-v45 task, and every all-no-shell task — hashes BYTE-IDENTICAL to before v45.
    That keeps existing confirmed tasks' stored `plan_hash` valid (no false plan-hash-mismatch
    stall on migration), mirroring the same back-compat carve-out `_verify_plan_hash` uses for
    `system_inserted`. Both hash sides stay in sync through this one function: `_verify_plan_hash`
    (`coordinator_graph.py`) and `full_dag_plan_hash` (`team_task_amend.py`) recompute over
    `TeamStep` rows, and `getattr(s, "needs_shell", False)` resolves on both `TeamStepPlan` and
    the persisted `TeamStep`."""
    import hashlib

    def _step_dict(s: Any) -> dict:
        d = {"step_id": s.step_id, "title": s.title, "assigned_to": s.assigned_to,
             "deps": list(s.deps)}
        if bool(getattr(s, "needs_shell", False)):
            d["needs_shell"] = True  # present only when True → all-False DAG hashes as pre-v45
        return d

    canonical = json.dumps(
        {"steps": [_step_dict(s) for s in task.steps]},
        sort_keys=True, ensure_ascii=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
