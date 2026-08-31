"""`assign_team_task` ops-chat command: CEO brief → decomposed DAG → confirmed team task.

Split out of `ops_catalog.py` (kept under the repo's ~200 LOC guideline) because this
command's `preview`/`run` need real collaborators (LLM, staff registry, the team-task
store) beyond a simple slot → admin-primitive call, unlike every other catalog entry.

Flow (mirrors `ops_chat.py`'s existing collect → preview → confirm state machine,
`OpsDraft.slots` is the only channel between the two calls):

  1. `preview(slots)` (called once, when the `brief` slot is finally filled): mints a
     `task_id`, runs ONE bounded decompose LLM call (retry on validation failure, capped
     — `_MAX_DECOMPOSE_ATTEMPTS`), validates the result in CODE (`validate_decomposition`),
     persists the PROPOSED plan via `TeamTaskStore.set_draft_plan` (status stays
     `planning` — not yet dispatchable), records the decompose LLM cost against the task,
     writes `task_id` + the plan's content hash into `slots` (so `run` can bind to the
     EXACT plan the CEO is about to see), and renders the full DAG as the confirmation
     text.
  2. `run(slots)` (called only after the CEO's explicit "xác nhận"): calls
     `TeamTaskStore.confirm_plan(task_id, plan_hash)` — TOCTOU-proof: it only flips the
     task to `open` (dispatchable by the coordinator ticker) if the hash still matches
     the plan `preview` persisted; it never re-decomposes or re-writes steps. A stale/
     mismatched hash reports a clean "kế hoạch đã đổi, thử lại" rather than dispatching a
     different plan than the one the CEO approved.
  3. `on_cancel(slots)` (called when the CEO's reply is NOT a confirm, i.e. "huỷ" or
     anything unclear): terminalizes the `planning` draft row via `cancel_draft` so it
     can never later be picked up by the ticker — a cancel-at-the-chat-layer alone
     (clearing only the `OpsConversationStore` draft) would leave the store's `planning`
     row abandoned but still `list_dispatchable`-invisible-yet-ticker-untouched forever;
     `cancel_draft` makes the abandonment terminal (status `cancelled`) instead of
     silently orphaned.
"""

from __future__ import annotations

import logging
import re

from my_crew.agent.sprint_intake import strip_mode_prefix
from my_crew.agent.task_decomposition import (
    DecompositionError,
    fanout_gap,
    fanout_split,
    find_terminals,
    fold_unjustified_steps,
    parse_decomposed_task,
    validate_decomposition,
)

logger = logging.getLogger(__name__)

#: Bounded retry for a malformed/invalid decomposition (schema violation, unknown
#: assignee, cycle, step-count) — re-prompts with the validation error appended, so a
#: transient model slip self-corrects instead of failing the whole command outright.
# 4 (v76 UAT): with the fan-out bias legitimately consuming one retry, two transient
# model hiccups (empty/refusal completions observed live with qwen) exhausted the old
# budget of 3 and failed the whole assign — one extra attempt is cheap insurance.
_MAX_DECOMPOSE_ATTEMPTS = 4


def _agent_has_operator_route(agent_id: str) -> bool:
    """The agent's own `telegram.ops_operator_id` is set AND in its `chat_ids`
    allowlist (`telegram_write.send_telegram_message` refuses any chat_id outside
    `chat_ids` — configured-but-not-allowlisted would silently drop every send)."""
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir

    try:
        loaded = load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    except (FileNotFoundError, RuntimeError):
        return False
    telegram = getattr(loaded.config, "telegram", None)
    operator = getattr(telegram, "ops_operator_id", "") if telegram else ""
    if not telegram or not operator:
        return False
    return operator in telegram.chat_ids


def _escalation_routable() -> bool:
    """True iff a `step_failed`/`step_timeout`/... escalation for THIS team task can
    actually reach the CEO on Telegram, via EITHER route `team_tick_collaborators
    .make_escalate` uses at escalation time:

    1. Fast path — the COORDINATOR agent's own Telegram binding (direct DM), or
    2. Mirror path — every escalation is also appended to the office room as a
       `milestone` event, and the admin agent's milestone-mirror pseudo-kind polls the
       room and DMs the CEO. So an enabled admin-domain agent with a working operator
       route makes escalations deliverable even when the coordinator has no bot of its
       own (the 1-click bootstrap coordinator ships without one).

    Checked at ASSIGN time (before a draft is even created) rather than discovered only
    when the first escalation silently fails days later. Hard block: a team task with
    no working escalation path at all has no safety net for a stuck/failed step.
    """
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.company import load_company
    from my_crew.runtime.registry import load_registry

    coordinator_id = load_company().coordinator_id
    if not coordinator_id:
        return False
    if _agent_has_operator_route(coordinator_id):
        return True
    # Mirror path: any enabled admin-domain agent with a working operator route.
    for entry in load_registry():
        if not entry.enabled:
            continue
        try:
            loaded = load_profile(entry.id, data_dir=agent_data_dir(entry.id))
        except (FileNotFoundError, RuntimeError):
            continue
        if getattr(loaded, "domain", "") == "admin" and _agent_has_operator_route(entry.id):
            return True
    return False


def _build_llm():
    from my_crew.config.config_builders import build_settings_from_env
    from my_crew.llm.client import LlmClient

    settings = build_settings_from_env()
    return LlmClient(settings), settings


def _staff_roster() -> list[tuple[str, str]]:
    """`[(agent_id, domain), ...]` for every ENABLED registry agent eligible for a
    team-task step — see `team_task_roster.assignable_staff` for the exclusion rules
    (coordinator + admin agent are never assignable) shared with the dispatch-time
    re-check (`task_decomposition.validate_decomposition`'s docstring)."""
    from my_crew.agent.team_task_roster import assignable_staff

    return assignable_staff()


#: v15 PIC prefix: "@<id> <việc>" — the CEO names the responsible staffer directly.
#: "@all <việc>" (or no @ at all) means "team decides": the decompose LLM proposes a
#: PIC instead (validated in code either way). Id charset mirrors registry ids.
_PIC_PREFIX_RE = re.compile(r"^@([A-Za-z0-9_.-]+)\s+(\S.*)$", re.S)


def parse_pic_prefix(brief: str) -> tuple[str, str]:
    """Split an optional leading @-mention off a CEO brief.

    Returns `(pic_requested, clean_brief)`: `"@content viết bài" -> ("content",
    "viết bài")`; `"@all ..."` and a brief with no leading @ both return `("", ...)`
    (LLM proposes the PIC). Whether `pic_requested` is actually assignable is the
    CALLER's check (roster in hand there) — this is pure text parsing."""
    m = _PIC_PREFIX_RE.match(brief.strip())
    if not m:
        return "", brief.strip()
    handle, rest = m.group(1), m.group(2).strip()
    if handle.lower() == "all":
        return "", rest
    return handle, rest


def _repair_terminal_assignee(task, staff_ids: set[str], pic_requested: str):
    """Hand the final synthesis step back to the PIC when the model gave it away.

    The prompt already states the rule in bold and the model still breaks it, so
    every violation used to cost a full re-prompt. Reassigning is the whole fix: the
    DAG shape, the step list and every other assignment stay put, and the PIC owning
    the terminal step is exactly what the invariant demands. Only the unambiguous
    case is repaired — with several terminals, *which* one is final is a judgement
    about the work, so that still goes back to the model. Best-effort: the validator
    downstream stays the only gate.
    """
    pic = pic_requested or task.pic_id
    if not pic or pic not in staff_ids:
        return task
    terminals = find_terminals(task.steps)
    if len(terminals) != 1 or terminals[0].assigned_to == pic:
        return task
    terminal = terminals[0]
    logger.info(
        "assign_team_task: code-side repair — terminal step [%s] reassigned %s → PIC %s",
        terminal.step_id, terminal.assigned_to, pic,
    )
    return task.model_copy(update={"steps": tuple(
        s.model_copy(update={"assigned_to": pic}) if s.step_id == terminal.step_id else s
        for s in task.steps
    )})


def _decompose_with_retries(
    brief: str, staff: list[tuple[str, str]], pic_requested: str = "",
) -> tuple:
    """Run the bounded decompose loop. Returns `(DecomposedTask, total_cost_usd)`.

    `pic_requested` (v15): the CEO's @-named PIC — rides into the prompt as a hard
    instruction AND into `validate_decomposition(pic_id=...)` as a code-side override
    (red-team F4: the model's own `pic_id` can never swap a CEO-named one). Blank ⇒
    the model proposes `pic_id` itself and validation runs against that proposal.

    Raises `DecompositionError` (CEO-facing message) if every attempt fails — either the
    model's output never validated, or there is no staff to assign to at all.
    """
    from my_crew.llm.team_task_prompt import build_team_decompose_messages

    if not staff:
        raise DecompositionError("chưa có nhân sự nào để giao việc — hãy tạo agent trước")

    llm, _settings = _build_llm()
    total_cost = 0.0
    last_error = ""
    for _attempt in range(_MAX_DECOMPOSE_ATTEMPTS):
        messages = build_team_decompose_messages(
            brief=brief, staff=staff, retry_error=last_error, pic_requested=pic_requested,
        )
        result = llm.complete(messages, role="plan")
        if result.cost_usd:
            total_cost += result.cost_usd
        # A body cut off by the output-token limit is a PREFIX, not an answer: it fails
        # JSON parsing exactly like model garbage does, but retrying with "your JSON was
        # malformed" makes the model write the same too-long plan again. Name the real
        # cause so the retry asks for a SHORTER plan — the only thing that can fix it.
        if getattr(result, "truncated", False):
            last_error = (
                "câu trả lời trước bị cắt cụt vì quá dài — hãy trả lời NGẮN GỌN hơn: "
                "ít bước hơn, mô tả mỗi bước ngắn hơn, không thêm giải thích ngoài JSON"
            )
            logger.warning(
                "assign_team_task: decompose bị cắt cụt (finish_reason=%r) — "
                "thử lại với yêu cầu rút ngắn",
                getattr(result, "finish_reason", ""),
            )
            continue
        try:
            task = parse_decomposed_task(result.content)
            task = _repair_terminal_assignee(
                task, {a for a, _ in staff}, pic_requested)
            task = validate_decomposition(
                task, staff_ids={a for a, _ in staff},
                pic_id=pic_requested if pic_requested else None,
            )
            # v15 acceptance (review M1): every NEW task gets a PIC — when the CEO
            # didn't @-name one, the model MUST propose it; an empty pic_id would
            # silently skip every PIC rule. Enforced here (not inside
            # validate_decomposition) because the amend path legitimately validates
            # pre-v15 tasks whose pic_id is "".
            if not task.pic_id:
                raise DecompositionError(
                    "thiếu pic_id — phải chọn MỘT nhân sự chịu trách nhiệm chính (PIC)"
                )
            # v64 shell guard: a needs_shell step nobody can run must fail HERE (the
            # retry loop lets the model drop the flag) — never at dispatch time.
            from my_crew.agent.team_task_roster import (
                validate_mail_steps,
                validate_shell_steps,
            )

            validate_shell_steps(task.steps)
            # v92 mail guard, same shape and same reason: a needs_mail step assigned to
            # an agent without mailbox access is caught here, not after it has spent a
            # step's budget answering "em không có quyền".
            validate_mail_steps(task.steps)
            # v74.2 fan-out bias: a ≥4-entity brief whose collection was NOT split
            # into parallel steps goes back through the retry loop with a concrete
            # instruction (measured: fanned ~11-12min vs un-fanned ~17-25min).
            # On the last attempt, code takes over from the model (code-paced beats
            # model-paced): `fanout_split` slices the packed collect step into 2-3
            # parallel entity-named steps deterministically. Only if the plan's shape
            # defeats the splitter does the old fail-open (accept the packed plan)
            # remain — a valid-but-slow plan always beats a failed assign.
            gap = fanout_gap(brief, task)
            if gap and _attempt < _MAX_DECOMPOSE_ATTEMPTS - 1:
                raise DecompositionError(gap)
            if gap:
                split = fanout_split(brief, task)
                if split is not None:
                    # Full re-validation (not just review policy): the split provably
                    # preserves acyclicity/staff/terminal, but proving it cheaply here
                    # beats trusting it — a rejected split falls back to the packed
                    # plan instead of failing the assign.
                    try:
                        task = validate_decomposition(
                            split, staff_ids={a for a, _ in staff},
                            pic_id=pic_requested if pic_requested else None,
                        )
                        logger.info(
                            "assign_team_task: code-side fan-out split the packed "
                            "collect step into %d parallel steps",
                            sum(1 for s in task.steps if s.needs_web and not s.deps),
                        )
                    except DecompositionError as split_exc:
                        logger.warning(
                            "assign_team_task: code-side fan-out rejected (%s) — "
                            "accepting un-fanned plan (%s)", split_exc, gap,
                        )
                else:
                    logger.warning(
                        "assign_team_task: accepting un-fanned plan after retries (%s)",
                        gap,
                    )
            # Graph-engineering fold (v93): a step that runs after ONE other step,
            # by the SAME person, with the SAME permissions has no real boundary
            # justifying its own node — merge it into its predecessor before hashing,
            # so the CEO confirms the plan that will actually run. Runs AFTER the
            # fan-out block: folding first would erase the packed-collect+finalize
            # shape `fanout_split` slices (measured live), while nothing the split
            # mints is ever a fold candidate (its parallel steps are dep-less, its
            # finalize multi-dep). Re-validated with the same cheap-proof-over-trust
            # fail-open as `fanout_split`: a rejected fold keeps the unfolded plan.
            folded, fold_count = fold_unjustified_steps(task)
            if fold_count:
                try:
                    task = validate_decomposition(
                        folded, staff_ids={a for a, _ in staff},
                        pic_id=pic_requested if pic_requested else None,
                    )
                    logger.info(
                        "assign_team_task: folded %d boundary-less step(s) — plan "
                        "now has %d step(s)", fold_count, len(task.steps),
                    )
                except DecompositionError as fold_exc:
                    logger.warning(
                        "assign_team_task: fold rejected (%s) — keeping the "
                        "unfolded plan", fold_exc,
                    )
            return _widen_terminal_deps(task), total_cost
        except DecompositionError as exc:
            last_error = str(exc)
            # Head of the raw completion rides the log (v76 UAT): "not valid JSON"
            # alone cannot distinguish an empty completion from prose or truncation.
            logger.warning("assign_team_task decompose attempt failed: %s (raw head: %r)",
                           exc, (result.content or "")[:120])
    raise DecompositionError(f"không phân rã được kế hoạch hợp lệ sau {_MAX_DECOMPOSE_ATTEMPTS} "
                             f"lần thử: {last_error}")


def _widen_terminal_deps(task):
    """The terminal (PIC synthesis) step depends DIRECTLY on every other step.

    A step's handoff is its direct deps' artifacts only — data does not flow
    transitively. The decompose prompt asks for this fan-in but models keep emitting
    linear chains (observed twice live: finalize deps=[qa] ⇒ the synthesis step could
    never see the research sources it must cite, no matter how many retries). Enforced
    in code, on the fresh-decompose path only: adding deps to the sink never changes
    scheduling order (everything already precedes it transitively), it only widens what
    the terminal step gets to read. Runs AFTER `validate_decomposition` (single
    terminal is proven) and BEFORE hashing/persist, so the CEO previews and confirms
    the widened DAG.
    """
    from my_crew.agent.task_decomposition import DecomposedTask

    dep_targets = {d for s in task.steps for d in s.deps}
    terminals = [s for s in task.steps if s.step_id not in dep_targets]
    if len(terminals) != 1 or len(task.steps) < 2:
        return task  # no/ambiguous terminal (validate already rejected) — leave as-is
    terminal = terminals[0]
    others = [s.step_id for s in task.steps if s.step_id != terminal.step_id]
    widened = terminal.model_copy(update={"deps": tuple(others)})
    steps = tuple(widened if s.step_id == terminal.step_id else s for s in task.steps)
    return DecomposedTask(steps=steps, pic_id=task.pic_id,
                          requires_approval=task.requires_approval)


def _render_plan(task) -> str:
    if _is_sprint_plan(task):
        step = task.steps[0]
        lines = [f"Chế độ SPRINT (một người làm trọn): {step.title}",
                 f"- Người làm: {step.assigned_to}"]
        if step.acceptance:
            lines.append("- Nghiệm thu:")
            lines.extend(f"  {ln.strip()}" for ln in step.acceptance.splitlines() if ln.strip())
        return "\n".join(lines)
    lines = ["Kế hoạch phân rã:"]
    for step in task.steps:
        deps_txt = f" (sau: {', '.join(step.deps)})" if step.deps else ""
        lines.append(f"- [{step.step_id}] {step.title} → {step.assigned_to}{deps_txt}")
    return "\n".join(lines)


def _is_sprint_plan(task) -> bool:
    """A sprint plan is the degenerate DAG: exactly one step carrying the sprint marker.

    The marker rides in `_SPRINT_STEP_IDS` rather than `step_type` because
    `DecomposedTask._step_type_bounds` reserves every non-"work" type for ticker-minted
    rows; the sprint step only becomes `step_type="sprint"` when it is written to the
    store (see `_step_type_for`), which is past that validator.
    """
    return len(task.steps) == 1 and task.steps[0].step_id == _SPRINT_STEP_ID


#: Step id of the single sprint step. Fixed (not model-chosen) so both the preview
#: renderer and the persist path can recognise a sprint plan without a side channel.
_SPRINT_STEP_ID = "sprint"


def _build_sprint_task(plan, pic_requested: str):
    """Wrap a `SprintPlan` in the SAME `DecomposedTask` shape team mode produces.

    Deliberately not a parallel type: everything downstream of this function (content
    hash, draft persist, confirm, kanban, cost) already speaks `DecomposedTask`, and a
    one-step DAG is a legal one. `step_type` stays "work" here — see `_is_sprint_plan`.
    """
    from my_crew.agent.task_decomposition import DecomposedTask, TeamStepPlan

    step = TeamStepPlan(
        step_id=_SPRINT_STEP_ID,
        title=plan.goal[:300],
        assigned_to=plan.assigned_to,
        deps=(),
        acceptance=plan.acceptance,
        # Sprint luôn mang cờ review: một bước chạy trọn trong một tiến trình là đường
        # zero-eyes duy nhất còn lại, nên bản giao nào cũng phải qua một con mắt thứ
        # hai trước khi đến CEO (`effective_needs_review` cũng không cho trusted miễn
        # cờ này). `pick_reviewer` không tìm được đồng nghiệp thì bỏ qua có ghi sổ.
        needs_review=True,
        # Both hardcoded because `sprint_refusal` sends shell/external-write briefs to
        # team mode before this runs — on BOTH paths, the heuristic and the CEO's
        # `sprint:` prefix. If that gate ever loosens, these two lines become the hole:
        # a shell step would route to the sandbox tier and silently drop `work_override`,
        # and an external-write step would lose its always-on review.
        needs_shell=False,
        needs_web=plan.needs_web,
        external_write=False,
    )
    return DecomposedTask(
        steps=(step,),
        pic_id=pic_requested or plan.assigned_to,
        requires_approval=True,
    )


def _plan_for_brief(brief: str, staff: list[tuple[str, str]], pic_requested: str,
                    forced_mode: str) -> tuple:
    """Pick the mode and produce `(DecomposedTask, cost_usd, is_sprint, route)`.

    The router lives HERE, before decompose, because this is the only place that has
    both the cleaned brief and the roster while nothing has been persisted yet — a
    later switch would mean writing a plan and rewriting it.

    An explicit `sprint:`/`team:` prefix from the CEO always wins over the heuristic.

    `route` is the observation record persisted alongside the task: which way it went,
    WHICH LAYER of the funnel decided, and the numbers that layer read. It exists so a
    later question — "are we still sending one-person work through the team machine?" —
    is answerable from the same table as the outcome, instead of by re-deriving the
    decision from a brief whose router has since changed.
    """
    from my_crew.agent.sprint_intake import (
        classify_brief,
        downgrade_to_sprint,
        route_signals,
        sprint_intake,
        sprint_refusal,
    )

    signals = route_signals(brief)

    def _route(mode: str, source: str, reason: str) -> dict:
        return {"mode": mode, "source": source, "reason": reason, "signals": signals}

    def _team_route(source: str, reason: str, task) -> dict:
        # Team routes carry the declared-boundary distribution of the ACCEPTED plan
        # (post-fold) next to the brief signals: lane stats can then answer "what
        # boundaries do our plans claim?" from the same table as the outcome.
        # Copied, not mutated — `signals` is shared by every `_route` closure.
        from my_crew.agent.task_decomposition import boundary_label_counts

        route = _route("team", source, reason)
        route["signals"] = {**signals,
                            "boundary_counts": boundary_label_counts(task)}
        return route

    def _team_plan(why_team: str, source: str) -> tuple:
        """Chạy decompose team, rồi hạ xuống sprint nếu kế hoạch hoá ra là việc 1 người.

        Lưới đỡ chiều team→sprint của bộ định tuyến (chiều ngược đã có: `sprint_dead_end`
        đẩy sprint bế tắc về team). Nhờ nó bộ đoán trên đề bài không cần đúng tuyệt đối:
        đoán thừa về phía team thì kế hoạch thật sẽ tự khai ra, và ta chỉ mất đúng lượt
        decompose vốn đã trả tiền.
        """
        task, cost = _decompose_with_retries(brief, staff, pic_requested)
        plan = downgrade_to_sprint(brief, task)
        if plan is None:
            return task, cost, False, _team_route(source, why_team, task)
        logger.info("assign_team_task: sprint mode (%s, nhưng kế hoạch suy biến %d bước "
                    "cùng %r)", why_team, len(task.steps), plan.assigned_to)
        return (_build_sprint_task(plan, pic_requested), cost, True,
                _route("sprint", "downgrade",
                       f"{why_team}; kế hoạch suy biến {len(task.steps)} bước 1 người"))

    if forced_mode == "team":
        # CEO gõ "team:" là quyết định của người giao việc, không phải phỏng đoán —
        # không hạ chế độ ở đây kể cả khi kế hoạch trông suy biến.
        logger.info("assign_team_task: team mode (CEO ép bằng tiền tố)")
        task, cost = _decompose_with_retries(brief, staff, pic_requested)
        return task, cost, False, _team_route("prefix", "CEO ép bằng tiền tố", task)

    if forced_mode == "sprint":
        # Tiền tố của CEO thắng bộ ĐOÁN, nhưng không gỡ được bốn loại trừ cứng: sprint
        # đóng cứng external_write/needs_shell = False, nên một đề ghi-ra-ngoài lọt vào
        # đây sẽ mất vòng review bắt buộc mà `review_insert` giữ cho đúng loại bước đó.
        refusal = sprint_refusal(brief)
        if refusal:
            # Không đi qua `_team_plan`: `downgrade_to_sprint` cũng từ chối đúng bốn loại
            # này, nên gọi vào đó chỉ tốn công — và đi thẳng giữ được ý "rào an toàn
            # thắng tiền tố" ở một chỗ đọc là thấy.
            logger.info("assign_team_task: team mode (CEO ép sprint nhưng %s)", refusal)
            task, cost = _decompose_with_retries(brief, staff, pic_requested)
            return (task, cost, False,
                    _team_route("refusal", f"CEO ép sprint nhưng {refusal}", task))
        want_sprint, reason, source = True, "CEO ép bằng tiền tố", "prefix"
    else:
        want_sprint, reason = classify_brief(brief)
        source = "refusal" if not want_sprint and sprint_refusal(brief) else "heuristic"
    logger.info("assign_team_task: %s mode (%s)", "sprint" if want_sprint else "team", reason)
    if not want_sprint:
        return _team_plan(reason, source)

    plan, cost = sprint_intake(brief, staff, pic_requested)
    route = _route("sprint", source, reason)
    # Bậc độ khó đi cùng bản ghi định tuyến chứ không thành cột riêng trong `team_steps`:
    # `route_json` vốn là chỗ chứa dữ liệu quan sát của chính lượt định tuyến này, nên
    # không phải nâng cấp lược đồ, và câu hỏi cần trả lời — "đề chấm high chết bao nhiêu
    # phần trăm" — được đọc từ đúng bảng đã giữ kết cục của task.
    route["effort"] = plan.effort
    if plan.effort == "high":
        # Cờ riêng bên cạnh `effort` để `route_stats` đếm được mà không phải hiểu thang
        # bậc; ở vòng này high CHỈ để đo, chưa được quyền đổi lane.
        route["effort_high"] = True
    return (_build_sprint_task(plan, pic_requested), cost, True, route)


def _title_from_brief(brief: str) -> str:
    """Tiêu đề task: CHỈ đoạn đầu của đề, cắt 120 ký tự.

    Cắt ở ranh giới đoạn chứ không cắt thẳng 120 ký tự đầu vì đề có thể mang thêm khối
    phụ do máy sinh ra ở đoạn sau — `upgrade_to_team` gắn bản nháp dở dang của chuyến
    sprint đã chết vào cuối đề. Tiêu đề đi thẳng vào tin nhắn gửi CEO
    (`milestone_mirror_runner` nội suy nguyên văn), nên một cửa sổ 120 ký tự thò được
    vào khối ấy là đường đưa chữ do LLM viết ra tới CEO mà không qua lớp bọc nào.

    Đề một đoạn — tức là gần như mọi đề CEO tự gõ — không đổi gì.
    """
    return brief.strip().split("\n\n", 1)[0].strip()[:120]


def preview_assign_team_task(slots: dict[str, str]) -> str:
    """Decompose the brief, persist the DRAFT plan, and render the full-DAG preview."""
    import uuid

    from my_crew.agent.task_decomposition import decomposition_content_hash
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    brief = slots.get("brief", "").strip()
    if not brief:
        raise ValueError("cần mô tả việc cần giao")

    if not _escalation_routable():
        raise ValueError(
            "Chưa có đường báo tin khi việc gặp sự cố, nên chưa giao việc được. "
            "Việc giao cho đội chạy nhiều bước và có thể kẹt giữa chừng — nếu không "
            "có đường báo về, bạn sẽ không biết. Cách thiết lập: mở trang Đội ngũ → "
            "chọn trưởng phòng điều phối → tab Kênh, dán token bot Telegram rồi bấm "
            "\"Lấy chat gần đây\" để chọn đúng chat của bạn. Xong quay lại đây "
            "giao việc lại."
        )

    # v77: "sprint:"/"team:" mode prefix strips FIRST (it wraps the whole brief),
    # then v15's "@<id> "/"@all " PIC prefix inside it.
    forced_mode, brief_after_mode = strip_mode_prefix(brief)
    pic_requested, clean_brief = parse_pic_prefix(brief_after_mode)
    staff = _staff_roster()
    if pic_requested and not any(a == pic_requested for a, _ in staff):
        raise ValueError(
            f"@{pic_requested} không có trong danh sách nhân sự có thể giao việc — "
            "kiểm tra lại mã nhân sự (hoặc dùng @all để đội tự chọn người chịu trách nhiệm)"
        )

    task, decompose_cost, is_sprint, route = _plan_for_brief(
        clean_brief, staff, pic_requested, forced_mode,
    )

    task_id = uuid.uuid4().hex[:12]
    plan_hash = decomposition_content_hash(task)
    # The sprint marker is stamped HERE, not on `TeamStepPlan`: the decompose schema
    # reserves every non-"work" step_type for ticker-minted rows, and the content hash
    # never reads step_type, so a sprint task's plan_hash is that of the same one-step
    # work DAG — confirm-time verification is unaffected.
    step_dicts = [
        {"step_id": s.step_id, "title": s.title, "assigned_to": s.assigned_to,
         "deps": list(s.deps), "acceptance": s.acceptance,
         "step_type": "sprint" if is_sprint else s.step_type,
         "needs_review": s.needs_review,
         "needs_shell": s.needs_shell,  # v45 tier-0 routing
         "needs_web": s.needs_web,  # v74 — hash-bound conditionally
         "external_write": s.external_write}  # v63 review-waiver + conditional hash
        for s in task.steps
    ]

    store = TeamTaskStore(team_tasks_db_path())
    try:
        store.create_task(task_id=task_id, title=_title_from_brief(clean_brief),
                          original_request=brief,
                          assigned_by="ceo-chat", pic_id=task.pic_id,
                          room_id=slots.get("room_id", "").strip())
        store.set_draft_plan(task_id, step_dicts, plan_hash)
        store.set_route(task_id, route)
        if decompose_cost:
            store.record_task_cost(task_id, decompose=decompose_cost)
    finally:
        store.close()

    # Bind the CEO's later confirm to THIS exact plan — see module docstring.
    slots["task_id"] = task_id
    slots["plan_hash"] = plan_hash
    slots["pic_id"] = task.pic_id
    # Which way the funnel routed (sprint | team) — the composer renders it as a badge
    # so the CEO sees the mode BEFORE confirming, not after the run starts.
    slots["route_mode"] = str(route.get("mode", ""))

    # Room event: the CEO's brief, appended to the (not-yet-dispatchable) task's own
    # room — try/degrade (a failed append must never block the preview/confirm flow).
    from my_crew.runtime.office_room_append import append_office_event, room_for_task

    append_office_event(room_for_task(task_id), author="ceo", kind="ceo", body={"text": brief})

    pic_line = f"\nPIC (chịu trách nhiệm chính): {task.pic_id}" if task.pic_id else ""
    # Vì sao việc này đi đường một-người hay cả-đội. Ghép ở ĐÂY chứ không trong
    # `_render_plan`: renderer đó chỉ nhận `task`, và kế hoạch đã persist không mang
    # theo bản ghi route — chỉ nơi này vừa có cả hai.
    from my_crew.agent.sprint_intake import render_route_reason

    route_reason = render_route_reason(route)
    route_line = f"\n{route_reason}" if route_reason else ""

    # v15 auto-confirm (Decision Q1 + red-team F3/F9): when the company flag is on,
    # confirm the JUST-previewed plan immediately with the SAME hash-bind path the CEO's
    # manual "xác nhận" uses — nothing about the bind/audit/room-event trail changes,
    # only who presses the button. `auto_confirmed` in slots tells the ops-chat state
    # machine NOT to park an awaiting_confirm draft (no ghost "huỷ/xác nhận" turn).
    from my_crew.agent.ops_autopilot import autopilot_enabled, brief_opts_out
    from my_crew.runtime.company import load_company

    # v63 per-task opt-out: an opt-out phrase in the brief ("để anh duyệt", ...) pins
    # THIS task to the manual gates for its whole life — the flag persists on the task
    # row (ticker autopilot decisions check it) and also blocks this turn's
    # auto-confirm below via the same `no_auto_confirm` mechanism v16 introduced.
    if brief_opts_out(brief):
        slots["no_auto_confirm"] = "1"
        store2 = TeamTaskStore(team_tasks_db_path())
        try:
            store2.set_require_ceo_approval(task_id, True)
        finally:
            store2.close()

    # getattr-default: pre-v15 Company doubles (tests) and any stale cached shape
    # simply mean "flag off" — the safe branch.
    # v63: `autopilot` implies auto-confirm (the CEO delegated the whole decision, the
    # plan-confirm button included) — same hash-bind path, same audit trail.
    if (getattr(load_company(), "team_task_auto_confirm", False) or autopilot_enabled()) \
            and not slots.get("no_auto_confirm"):
        # `no_auto_confirm` (v16 red-team M3): an LLM-classified chat intent may reuse
        # this preview but must NEVER inherit the auto-confirm privilege — only the
        # CEO's explicit hard-prefix commands (@/giao/chỉnh, or the composer button
        # flow) are allowed to skip the manual confirm.
        try:
            run_text = run_assign_team_task(slots)
        except Exception as exc:  # noqa: BLE001 — ANY auto-run failure (stale hash
            # ValueError, sqlite OperationalError, ...) must terminalize the planning
            # draft instead of orphaning it, then surface as a clean reply (F9).
            cancel_assign_team_task(slots)
            raise ValueError(f"tự xác nhận thất bại: {exc}") from None
        slots["auto_confirmed"] = "1"
        return (f"{_render_plan(task)}{pic_line}{route_line}\n\nMã việc: {task_id}\n"
                f"ĐÃ TỰ XÁC NHẬN (chế độ tự xác nhận đang bật) — {run_text}")

    return (f"{_render_plan(task)}{pic_line}{route_line}\n\nMã việc: {task_id}\n"
            "Xác nhận giao việc này cho đội? (trả lời: xác nhận / huỷ)")


def run_assign_team_task(slots: dict[str, str]) -> str:
    """Confirm-time: flip the EXACT previewed plan to `open` — never re-decompose."""
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    task_id = slots.get("task_id", "")
    plan_hash = slots.get("plan_hash", "")
    if not task_id or not plan_hash:
        raise ValueError("thiếu thông tin kế hoạch — hãy thử giao việc lại từ đầu")

    store = TeamTaskStore(team_tasks_db_path())
    try:
        confirmed = store.confirm_plan(task_id, plan_hash)
        task = store.get(task_id) if confirmed else None
    finally:
        store.close()
    if not confirmed:
        raise ValueError("kế hoạch đã thay đổi hoặc hết hạn — hãy thử giao việc lại từ đầu")

    # Room events: the confirmed DAG (assignment) + a milestone ("task received") — both
    # try/degrade, appended AFTER the store confirm so a failed append never undoes the
    # actual dispatch decision.
    from my_crew.runtime.office_room_append import append_office_event, room_for_task

    if task is not None:
        assignees = ", ".join(sorted({s.assigned_to for s in task.steps}))
        summary = f"Phân công: {assignees}"
        if task.pic_id:
            summary = f"PIC: {task.pic_id} — {summary}"
        # `pic`/`task_id` ride in the body (v15) so the FE can badge the PIC's desk and
        # later clear it on this task's `milestone: done` event (red-team F6 contract).
        append_office_event(
            room_for_task(task_id), author="coordinator", kind="assignment",
            body={"task_title": task.title, "step_count": len(task.steps),
                  "summary": summary, "pic": task.pic_id, "task_id": task_id},
            also_office=True,
        )
        append_office_event(
            room_for_task(task_id), author="coordinator", kind="milestone",
            body={"task_id": task_id, "task_title": task.title, "milestone": "received",
                  "message": f"Đội đã nhận việc '{task.title}' ({len(task.steps)} bước)."},
            also_office=True,
        )
    # v74.1: a freshly-confirmed task lands between two minute ticks — poke so the
    # first dispatch happens within a ~5s sleep slice instead of up to 60s later
    # (benchmark 18a8396a76fa measured a 30s first-dispatch wait). Best-effort inside.
    from my_crew.runtime.tick_poke import touch_poke

    touch_poke()
    return f"Đã giao việc #{task_id} cho đội — điều phối viên sẽ bắt đầu phân công."


def cancel_assign_team_task(slots: dict[str, str]) -> None:
    """`on_cancel` hook: the CEO declined/never confirmed the previewed plan.

    A missing `task_id` (preview never ran, or already cleared) is a silent no-op —
    there is nothing to cancel. `TeamTaskStore.cancel_draft` itself only terminalizes a
    row still in `planning`, so a race where `run_assign_team_task` already confirmed
    it (the CEO somehow both confirmed and this hook fired) is also a safe no-op.
    """
    task_id = slots.get("task_id", "")
    if not task_id:
        return
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    try:
        store.cancel_draft(task_id)
    finally:
        store.close()
