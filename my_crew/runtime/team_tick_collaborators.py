"""Coordinator-tick collaborator factories split out of `team_tick_runner.py` to keep
that module under the repo's ~200 LOC guideline: the aggregate (LLM summarize), room
delivery, and Telegram escalation callables `CoordinatorDeps` needs.
"""

from __future__ import annotations

import logging
from typing import Any

from my_crew.runtime.team_task_paths import team_tasks_root
from my_crew.runtime.team_task_store import TeamStep, TeamTask

logger = logging.getLogger(__name__)

#: Task-level `event_kind`s where the ticker has just moved the WHOLE task to
#: `stalled` (never a single-step-only failure that might still resolve via a later
#: tick's retry/other-step-completes path) — a full replan is the actually-relevant
#: remedy for these, so the escalation gets a suggested `adjust_team_task` command.
_STALL_EVENT_KINDS = frozenset({
    "task_stalled_dead_step", "plan_hash_mismatch", "review_rounds_exhausted",
    "cost_cap_exceeded",
})

#: CONSTANT template, `{task_id}` interpolation ONLY — deliberately never composed
#: from task content/LLM output. A message built from task/step titles (which can
#: carry text absorbed from a hostile CEO brief or a prior step's echoed injection)
#: could smuggle a misleading amend brief the CEO copy-pastes verbatim as a command;
#: this template carries no such content, only the stable, code-assigned task id.
_AMEND_SUGGESTION_TEMPLATE = (
    "\n\nCEO có thể chỉnh kế hoạch: `chỉnh kế hoạch {task_id}: <yêu cầu>`"
)

#: v63 one-touch suggestions — same constant-template rule as above (`{task_id}` only).
_ONE_TOUCH_SUGGESTION_TEMPLATE = (
    "\nXử nhanh: `accept_stalled_result {task_id}` (chấp nhận kết quả) · "
    "`retry_stalled_step {task_id}` (thử thêm 1 lượt) · "
    "`drop_stalled_step {task_id}` (bỏ bước chết)"
)

#: v78 sprint dead-end, một chạm. Cùng luật hằng-số như hai template trên: chỉ nội suy
#: `{task_id}` do code sinh, không bao giờ ghép từ tiêu đề việc/bước.
#:
#: v77 chỉ nói "CEO giao lại bằng tiền tố `team:`" — nghĩa là CEO tự gõ lại đề và mọi
#: thứ chuyến sprint vừa làm ra rơi xuống đất. `upgrade_to_team` dựng việc mới mang
#: theo bản nháp dở dang, nên lời mời nêu đúng mã việc cần nâng.
#:
#: Lời mời nêu một LỆNH, không nêu người: bước sprint chỉ có một người chạy, nên
#: `reassign` chỉ đổi sang một agent khác chạy đúng pipeline đó — "nhờ người khác" là
#: cách chữa duy nhất chắc chắn không giúp được gì ở đây.
_SPRINT_UPGRADE_SUGGESTION = (
    "\nViệc này chạy chế độ nhanh (1 người, pipeline ngắn) và đã bế tắc. "
    "Giao lại cho cả đội kèm kết quả dở dang: `upgrade_to_team {task_id}`"
)

#: Autopilot đã tự nâng cấp — nêu id việc MỚI để CEO theo dõi được, và nói rõ việc cũ
#: vẫn nằm đó. Constant template, chỉ nội suy id do code sinh, như mọi template khác.
_SPRINT_UPGRADED_TEMPLATE = (
    "\nViệc này chạy chế độ nhanh (1 người) và đã bế tắc, nên mình đã tự giao lại cho "
    "cả đội kèm kết quả dở dang: việc mới `{new_task_id}`. Việc cũ giữ nguyên để đối chiếu."
)


def _is_sprint_dead_end(task: TeamTask, event_kind: str) -> bool:
    """True when this escalation ends a task whose only content step was a sprint.

    Gated on `gave_up` alone: the earlier `stuck` escalations are rulings that PUT THE
    STEP BACK to pending, so suggesting a mode change there would talk the CEO into
    abandoning a task the coordinator is still actively retrying.
    """
    if event_kind != "gave_up":
        return False
    steps = getattr(task, "steps", None) or ()
    return any(getattr(s, "step_type", "") == "sprint" for s in steps)


def _mark_route_dead_end(task_id: str) -> None:
    """Ghi vào bản ghi định tuyến rằng chuyến sprint này đã bế tắc.

    Đây là dòng phản hồi duy nhất nói bộ định tuyến ĐOÁN SAI về phía sprint, nên nó
    phải nằm cùng chỗ với quyết định ban đầu để sau này đếm được tỉ lệ sai. Quyết
    định gốc giữ nguyên trong khoá `previous`: cái đáng học là "đường nào dẫn tới bế
    tắc", không phải chỉ "có bế tắc".

    try/degrade như mọi thứ khác trong `_escalate`: đây là dữ liệu quan sát, hỏng thì
    ghi log — không bao giờ được chặn một cảnh báo đang trên đường tới CEO.
    """
    try:
        from my_crew.runtime.team_task_paths import team_tasks_db_path
        from my_crew.runtime.team_task_store import TeamTaskStore

        store = TeamTaskStore(team_tasks_db_path())
        try:
            route = store.get_route(task_id)
            if route is None or route.get("source") == "dead_end":
                return
            store.set_route(task_id, {**route, "source": "dead_end", "previous": route})
        finally:
            store.close()
    except Exception:
        logger.warning("không ghi được dấu bế tắc sprint vào route_json (%s)",
                       task_id, exc_info=True)


def _route_reason_block(task_id: str) -> str:
    """Dòng "việc này đang chạy đường nào và vì sao", cho cảnh báo kẹt.

    CEO đọc một cảnh báo kẹt rồi phải quyết đổi chế độ hay không; không nói việc này
    ĐANG chạy đường nào và vì sao thì quyết định đó là đoán mò. Task trước v77 không
    có bản ghi route — trả rỗng, không bịa.

    try/degrade như `_mark_route_dead_end`: đây là phần trang trí có ích, không bao
    giờ được chặn một cảnh báo đang trên đường tới CEO.
    """
    try:
        from my_crew.agent.sprint_intake import render_route_reason
        from my_crew.runtime.team_task_paths import team_tasks_db_path
        from my_crew.runtime.team_task_store import TeamTaskStore

        store = TeamTaskStore(team_tasks_db_path())
        try:
            line = render_route_reason(store.get_route(task_id))
        finally:
            store.close()
    except Exception:
        logger.warning("không đọc được route_json để dựng dòng lý do (%s)",
                       task_id, exc_info=True)
        return ""
    return f"\n{line}" if line else ""


def _sprint_upgrade_tail(task: TeamTask) -> str:
    """Phần đuôi cho một cảnh báo sprint bế tắc: tự nâng cấp, hoặc mời CEO bấm.

    Autopilot bật nghĩa là CEO đã uỷ quyền cho máy gỡ việc bị dừng, và đây đúng là một
    việc bị dừng. Nhưng vẫn CHỈ MỘT LẦN cho mỗi chuỗi: `upgrade_to_team` từ chối nâng
    một task vốn đã là bản nâng cấp, nên chuỗi nâng→chết→nâng tự dừng ở mắt thứ hai và
    rơi về đúng lời mời thủ công bên dưới.

    Nâng cấp hỏng vì bất cứ lý do gì cũng chỉ hạ xuống lời mời thủ công: cảnh báo phải
    tới CEO kèm MỘT cách chữa dùng được, không bao giờ được nổ giữa đường.
    """
    try:
        from my_crew.agent.ops_autopilot import autopilot_enabled

        if not autopilot_enabled() or getattr(task, "require_ceo_approval", False):
            return _SPRINT_UPGRADE_SUGGESTION.format(task_id=task.id)
    except Exception:  # noqa: BLE001 — không đọc được cờ thì coi như tắt
        logger.warning("không đọc được cờ autopilot khi sprint bế tắc (%s)",
                       task.id, exc_info=True)
        return _SPRINT_UPGRADE_SUGGESTION.format(task_id=task.id)

    try:
        from my_crew.agent.ops_upgrade_to_team import run_upgrade_to_team

        slots: dict[str, str] = {"task_id": task.id}
        run_upgrade_to_team(slots)
        new_id = slots.get("new_task_id", "")
    except Exception as exc:  # noqa: BLE001 — mọi thất bại đều rơi về lối thủ công
        logger.warning("autopilot: không tự nâng cấp được việc sprint %s (%s)",
                       task.id, exc)
        return _SPRINT_UPGRADE_SUGGESTION.format(task_id=task.id)

    if not new_id or new_id == task.id:
        return _SPRINT_UPGRADE_SUGGESTION.format(task_id=task.id)

    try:
        from my_crew.agent.ops_autopilot import record_autopilot_decision

        record_autopilot_decision(
            decision="upgrade_to_team", task_id=task.id, task_title=task.title,
            detail=f"việc chạy nhanh bế tắc — đã giao lại cho cả đội thành `{new_id}`",
        )
    except Exception:  # noqa: BLE001 — audit không bao giờ chặn thứ nó ghi lại
        logger.exception("autopilot: không ghi được nhật ký nâng cấp cho %s", task.id)
    return _SPRINT_UPGRADED_TEMPLATE.format(new_task_id=new_id)


def _review_evidence_block(task: TeamTask, step: TeamStep | None) -> str:
    """v63 evidence pack: the failing round's verdict summary, so the CEO/secretary can
    decide accept/retry/drop from the escalation alone. The failure lines are reviewer
    LLM output (second-order untrusted) — wrapped through `format_internal_content`,
    never concatenated raw into the constant template. Empty string on any miss:
    evidence is best-effort garnish, never a reason an escalation fails to send."""
    if step is None:
        return ""
    try:
        from my_crew.agent.team_task_artifact import read_review_verdict_artifact
        from my_crew.tools.search_result_formatter import format_internal_content

        reviews = [s for s in task.steps
                   if s.step_type == "review" and s.parent_step_id == step.step_id]
        for review in sorted(reviews, key=lambda s: s.seq, reverse=True):
            verdict = read_review_verdict_artifact(
                team_tasks_root(), task.id, step.seq, review.review_round,
            )
            if verdict is None or bool(verdict.get("passed")):
                continue
            # Truncate BEFORE wrapping (review M1): slicing the wrapped text could
            # sever `format_internal_content`'s closing delimiter, leaving an
            # unterminated untrusted block right before the command suggestions.
            failures = [str(f)[:150] for f in list(verdict.get("failures") or [])[:3]]
            if not failures:
                return ""
            wrapped = format_internal_content(
                "\n".join(f"- {f}" for f in failures), label="lý do soát chéo không đạt",
            )
            return f"\n\nLý do vòng soát cuối không đạt:\n{wrapped}"
    except Exception:  # noqa: BLE001 — evidence must never break the escalation itself
        logger.exception("team-tick: evidence block failed for task %s", task.id)
    return ""


def _content_dep_targets(task: TeamTask) -> set[str]:
    """Step ids that another CONTENT step feeds into.

    Terminality is a property of the plan, and the plan is the content steps. A review
    (and the rework it mints) always declares a dep on the step it audits, so counting
    those rows would make every reviewed terminal look non-terminal — the whole shape
    collapses to zero terminals the moment one review exists. The plan-time terminal
    checks in `task_decomposition` can use a bare dep scan because they run before any
    review row is minted; this one runs at delivery time, after.
    """
    return {
        d for s in task.steps if s.step_type in ("work", "sprint") for d in s.deps
    }


def _current_result_text(task: TeamTask, step: TeamStep) -> str:
    """`step`'s deliverable text, preferring its latest done rework.

    A failed verdict mints a rework that writes its corrected output to ITS OWN seq, so
    reading the original step's seq unconditionally would hand the CEO the exact draft
    the reviewer had just rejected. Latest done rework (highest seq) is the current truth.
    """
    from my_crew.agent.team_task_artifact import read_step_artifact

    reworks = [
        s for s in task.steps
        if s.step_type == "rework" and s.parent_step_id == step.step_id
        and s.status == "done"
    ]
    seq = max(reworks, key=lambda s: s.seq).seq if reworks else step.seq
    artifact = read_step_artifact(team_tasks_root(), task.id, seq)
    return str((artifact or {}).get("result_text") or "").strip()


def _direct_result_text(task: TeamTask) -> str:
    """The full result text to hand the CEO verbatim, or "" to use the normal path.

    v77 established this for the sprint shape: the artifact was written to be READ, so
    summarizing it pays a second LLM call to compress the only thing that matters.

    The same holds whenever the plan converges on ONE terminal content step — the step
    every other step feeds into. Asking the model to "tóm tắt" that artifact turns a
    finished deliverable into a description of itself: observed live (task
    1049321b5b2d), a 4-step article task whose steps all passed review delivered
    "Bước 2: Đã viết xong bản thảo ..." to a CEO who had asked for the article.
    Multiple terminals still take the summarize path — there the CEO genuinely needs
    several outputs woven together, which is what the aggregate call is for.

    "" whenever the shape does not apply or the artifact went missing, so a lost file
    degrades to the usual summary rather than delivering nothing.
    """
    content = [s for s in task.steps if s.step_type in ("work", "sprint")]
    if not content:
        return ""
    if len(content) == 1 and content[0].step_type == "sprint":
        return _current_result_text(task, content[0])
    terminals = [s for s in content if s.step_id not in _content_dep_targets(task)]
    if len(terminals) != 1:
        return ""
    return _current_result_text(task, terminals[0])


def make_aggregate(loaded: Any, settings: Any):
    """One LLM call summarizing every step's handoff artifact into a room-ready message.
    Falls back to a deterministic (no-LLM) join of step titles/results on any LLM
    failure — an aggregate must never block a task stuck at 100%-done from being marked
    `done` just because the summarizing call itself failed.

    Second-order injection: each step's `result_text` is not automatically
    trusted just because it was produced inside this codebase — it may itself echo an
    injection phrase absorbed from a web-search result or a hostile CEO brief that step
    read. The LLM-summarize prompt (not the plain-join fallback, which never reaches a
    model) wraps every step's snippet through `search_result_formatter
    .format_internal_content` — same delimiter/scan/spotlight treatment a first-order
    external source gets — before folding it into the aggregate prompt.
    """

    def _aggregate(task: TeamTask) -> tuple[str, float | None]:
        from my_crew.agent.ops_stalled_task import (
            DROP_PLACEHOLDER_PREFIX,
            DROP_REASON_PREFIX,
        )
        from my_crew.agent.team_task_artifact import (
            read_review_verdict_artifact,
            read_step_artifact,
        )
        from my_crew.tools.search_result_formatter import format_internal_content

        seq_by_step_id = {s.step_id: s.seq for s in task.steps}
        # A terminal step's artifact IS the deliverable the CEO asked for — the same
        # reasoning v77 applied to the sprint step, one shape up. Truncating it at 500
        # chars like an intermediate handoff makes the summarizer describe a cut-off
        # text instead of delivering it: observed live (task 1049321b5b2d), every step
        # passed review yet the CEO received "bản thảo bị cắt giữa chừng ... không thể
        # xác nhận đầy đủ toàn văn" instead of the 400-500 word article. Intermediate
        # steps keep the cap — their detail already reached the terminal through the
        # deps handoff, and the prompt must stay bounded.
        dep_targets = _content_dep_targets(task)
        terminal_ids = {
            s.step_id for s in task.steps
            if s.step_type in ("work", "sprint") and s.step_id not in dep_targets
        }
        parts: list[str] = []
        note_lines: list[str] = []
        gap_lines: list[str] = []
        for step in sorted(task.steps, key=lambda s: s.seq):
            if step.step_type == "review":
                # v63 "đạt kèm góp ý": a passed review's notes are worth surfacing in
                # the CEO summary (they never minted a rework, so this is their only
                # delivery path). A failed review's failures already reach the CEO
                # through the rework round it minted — no separate line needed.
                content_seq = seq_by_step_id.get(step.parent_step_id or "")
                verdict = (
                    read_review_verdict_artifact(
                        team_tasks_root(), task.id, content_seq, step.review_round,
                    )
                    if content_seq is not None else None
                )
                notes = list(verdict.get("notes") or []) if verdict else []
                if verdict and bool(verdict.get("passed")) and notes:
                    joined = "; ".join(str(n)[:200] for n in notes[:5])
                    line = f"- {step.title}: đạt — góp ý thêm: {joined}"
                    parts.append(line)
                    note_lines.append(line)
                continue
            artifact = read_step_artifact(team_tasks_root(), task.id, step.seq)
            text = ""
            if artifact:
                text = str(artifact.get("result_text") or artifact.get("status") or "")
            # A dropped step's placeholder means the delivery has a real hole in it.
            # Naming the hole is done in CODE (deterministic header below), not by
            # hoping the summarizer LLM mentions it — and the header must NEVER use
            # the abandonment phrase "KHÔNG LÀM ĐƯỢC": that is the give_up marker for
            # a task that delivered nothing, while this task DID deliver.
            if text.startswith(DROP_PLACEHOLDER_PREFIX):
                skip_reason = next(
                    (line[len(DROP_REASON_PREFIX):].strip()
                     for line in text.splitlines()
                     if line.startswith(DROP_REASON_PREFIX)),
                    "",
                )
                gap_lines.append(
                    f"bước '{step.title}' bỏ qua vì {skip_reason}" if skip_reason
                    else f"bước '{step.title}' đã chủ động bỏ qua"
                )
            # A rework rides on its parent's terminality: it REPLACES that step's
            # output, so cutting it would re-open the same hole one round later.
            is_terminal = (
                step.step_id in terminal_ids
                or (step.step_type == "rework" and step.parent_step_id in terminal_ids)
            )
            if not text:
                snippet = "(không có kết quả)"
            else:
                snippet = text if is_terminal else text[:500]
            parts.append(f"- {step.title}: {snippet}")
        gap_header = (
            "Hoàn thành với khoảng trống: " + "; ".join(gap_lines) + ".\n\n"
            if gap_lines else ""
        )
        fallback_summary = (
            gap_header + f"Việc '{task.title}' đã hoàn tất:\n" + "\n".join(parts)
        )

        # A task converging on ONE terminal content step delivers that artifact
        # verbatim — see `_direct_result_text` for why summarizing it is the wrong
        # operation. This returns before `format_internal_content` runs, which is
        # harmless: that pass strips the LLM's summary-shaped scaffolding, and a step
        # artifact has none — it went through the same `deliver` path every work step's
        # output does.
        direct = _direct_result_text(task)
        if direct:
            # A passed-with-notes review never mints a rework, so this summary is the
            # only path its advisory notes have to the CEO — handing back the artifact
            # alone would silently drop them (v63 behaviour, kept intact here).
            if note_lines:
                return gap_header + direct + "\n\n" + "\n".join(note_lines), None
            return gap_header + direct, None

        if not settings.openrouter_api_key:
            return fallback_summary, None
        try:
            from my_crew.llm.client import LlmClient

            wrapped_parts = [
                format_internal_content(p, label=f"step-{i + 1}") or p
                for i, p in enumerate(parts)
            ]
            client = LlmClient(settings)
            # "Bắt đầu NGAY bằng bản tóm tắt": some models (observed: qwen3.7-plus)
            # write an English chain-of-thought preamble into content; Telegram then
            # truncates at 4096 chars and the CEO receives ONLY the preamble — the
            # actual Vietnamese summary is cut off entirely.
            prompt = (
                f"Tóm tắt ngắn gọn (tiếng Việt) kết quả của việc '{task.title}' cho "
                "CEO, dựa trên các bước sau. QUY TẮC TRUNG THỰC: bước nào ghi 'KHÔNG "
                "CÓ KẾT QUẢ'/bị bỏ qua thì phải nêu rõ là thiếu dữ liệu — tuyệt đối "
                "không suy diễn hay bịa số liệu thay cho bước đó. ĐỊNH DẠNG: bắt đầu "
                "câu trả lời NGAY bằng bản tóm tắt tiếng Việt hoàn chỉnh, dưới 3000 "
                "ký tự; KHÔNG viết quá trình suy nghĩ, không lời dẫn, không phân tích "
                "meta, không tiếng Anh.\n\n"
                + "\n\n".join(wrapped_parts)
            )
            result = client.complete(
                [{"role": "user", "content": prompt}], role="aggregate"
            )
            if result.content:
                return gap_header + result.content, result.cost_usd
            return fallback_summary, result.cost_usd
        except Exception:  # noqa: BLE001 — never let a summarizer failure block delivery
            logger.exception("team-tick: aggregate LLM call failed for task %s", task.id)
            return fallback_summary, None

    return _aggregate


def make_deliver_room(loaded: Any = None, settings: Any = None):
    """Posts the aggregate summary to the group room as a "task done" milestone (also
    mirrored into the shared office room — `also_office=True`). Never raises, but since
    v67 REPORTS whether the milestone actually landed: this event is what the admin
    milestone mirror DMs the CEO from, so a swallowed failure here used to mean "task
    done, CEO never told, nothing retries". The bool feeds `delivery_status` +
    the delivery-retry sweep.

    `loaded`/`settings` (optional): enables the same coordinator-Telegram FAST PATH
    `make_escalate` has. Without it, "done" reached the CEO only via the admin mirror
    bot while stall/stuck escalations arrived in the ASSIGNING bot's chat — the CEO
    watched the conversation they gave the task in and concluded no completion notice
    ever came (observed live, task 03a49412fd12). The mirror stays the guaranteed
    path; this send is best-effort low-latency and its failure never affects the
    returned delivery bool."""

    def _deliver(task: TeamTask, summary: str) -> bool:
        from my_crew.runtime.office_room_append import (
            append_office_event_checked,
            room_for_task,
        )

        logger.info("team-tick: task %s aggregate ready: %s", task.id, summary[:200])
        # Whether the direct (fast-path) send below succeeded — stamped into the room
        # milestone body so the mirror can SKIP re-pushing a notice the CEO already
        # has: with both channels now landing in the SAME chat, the digest was an
        # immediate duplicate of the ✅ message (observed on the CEO's phone).
        sent_direct = False
        if loaded is not None and settings is not None:
            try:
                from my_crew.actions.action_gateway import ActionGateway
                from my_crew.actions.telegram_write import (
                    send_telegram_message,
                    with_tail,
                )

                telegram = getattr(loaded.config, "telegram", None)
                operator = getattr(telegram, "ops_operator_id", "") if telegram else ""
                if telegram and operator:
                    gateway = ActionGateway(
                        settings,
                        external_channels=loaded.config.slack_external_channels,
                        actor=getattr(loaded, "profile_id", ""),
                    )
                    from my_crew.runtime.dashboard_links import workroom_url

                    # No title prefix when the summary already opens with the task name
                    # — the CEO was reading the full title three times per message.
                    # A give-up conclusion also flows through here (stuck_decision
                    # reuses the delivery path for its honest final summary) — that
                    # message must NOT carry a completion checkmark.
                    if "KHÔNG LÀM ĐƯỢC" in summary[:160]:
                        head = "⛔ "
                    else:
                        head = ("✅ HOÀN THÀNH — " if summary.lstrip().startswith("Việc")
                                else f"✅ Việc '{task.title[:120]}' — HOÀN THÀNH:\n\n")
                    try:
                        result = send_telegram_message(
                            with_tail(
                                f"{head}{summary}",
                                f"\n\n🔎 Chi tiết đầy đủ: {workroom_url(task.id)}",
                            ),
                            gateway=gateway, telegram=telegram, chat_id=operator,
                            dedup_hint=f"team-tick:{task.id}:done",
                            rationale="task-done fast path to the assigning chat",
                        )
                        sent_direct = result.status in ("executed", "pending_approval")
                    finally:
                        gateway.close()
            except Exception:  # noqa: BLE001 — fast path only; the mirror still delivers
                logger.exception("team-tick: done fast-path send failed for task %s",
                                 task.id)
        landed = append_office_event_checked(
            room_for_task(task.id), author="coordinator", kind="milestone",
            body={"task_id": task.id, "task_title": task.title, "milestone": "done",
                  "message": summary, "delivered_direct": sent_direct},
            also_office=True,
        )
        return landed

    return _deliver


def make_escalate(loaded: Any, settings: Any):
    """Telegram escalation, mirroring `ops_alert_runner.run_ops_alerts`'s exact
    gateway-construction + `send_telegram_message` call shape. try/degrade: any failure
    (no operator configured, gateway/network error) is logged and swallowed — this
    callable's documented contract (`CoordinatorDeps.escalate`) is "never raises"."""

    def _escalate(task: TeamTask, step: TeamStep | None, event_kind: str, message: str) -> None:
        if event_kind == "review_rounds_exhausted":
            message = message + _review_evidence_block(task, step)
        if event_kind in _STALL_EVENT_KINDS:
            message = (message + _route_reason_block(task.id)
                       + _AMEND_SUGGESTION_TEMPLATE.format(task_id=task.id)
                       + _ONE_TOUCH_SUGGESTION_TEMPLATE.format(task_id=task.id))
        if _is_sprint_dead_end(task, event_kind):
            message = message + _route_reason_block(task.id) + _sprint_upgrade_tail(task)
            _mark_route_dead_end(task.id)

        # Whether the direct (fast-path) send below succeeded. Stamped into the room
        # milestone body so the mirror SKIPS re-pushing a notice the CEO already has —
        # the same `delivered_direct` contract `_deliver` uses. Without it every
        # escalation reached the CEO twice: once as its own message, then again inside
        # the "🏁 Cập nhật tiến độ đội" digest, since both channels now land in the
        # SAME chat. The send therefore has to run BEFORE the append; the append itself
        # stays unconditional, so the mirror is still the guaranteed delivery path when
        # the coordinator has no bot binding of its own.
        sent_direct = _escalate_direct(task, step, event_kind, message)
        try:
            from my_crew.runtime.office_room_append import append_office_event, room_for_task

            body = {"task_id": task.id, "task_title": task.title, "milestone": event_kind,
                    "message": message, "delivered_direct": sent_direct}
            # Emitted only when this escalation is ABOUT a specific step, which keeps
            # every task-level escalation's body byte-identical to before. The mirror
            # dedups per-step milestones (`stuck`, `step_failed`) on this key — without
            # it, two different stuck steps on one task collapse into a single daily
            # Telegram push and the CEO only ever hears about the first one.
            if step is not None:
                body["step_id"] = step.step_id
                # How many times the coordinator has already ruled on THIS step. The
                # mirror folds it into the dedup key for recurring per-step milestones,
                # so a second intervention on the same step in the same day still
                # reaches the CEO instead of being swallowed as a duplicate.
                body["attempt"] = getattr(step, "intervention_count", 0)
            append_office_event(
                room_for_task(task.id), author="coordinator", kind="milestone",
                body=body, also_office=True,
            )
        except Exception:  # noqa: BLE001 — escalation must never crash the ticker
            logger.exception("team-tick: escalate(%s) room append failed for task %s",
                             event_kind, task.id)

    def _escalate_direct(
        task: TeamTask, step: TeamStep | None, event_kind: str, message: str,
    ) -> bool:
        """Low-latency send straight to the operator. Returns whether the CEO can
        be assumed to have this message already — the mirror reads that to decide
        whether the digest would be a duplicate. False on every degrade path (no
        channel configured, gateway/network error), which keeps the mirror as the
        fallback. Channel choice lives in `operator_notify`: Telegram when bound,
        otherwise email or webhook, so an operator who does not use Telegram still
        gets pushed instead of having to go look in the web app."""
        try:
            from my_crew.runtime.operator_channels import send_via_channels

            step_id = step.step_id if step is not None else ""
            return bool(send_via_channels(
                message,
                loaded=loaded,
                settings=settings,
                dedup_hint=f"team-tick:{task.id}:{step_id}:{event_kind}",
                rationale=f"team task escalation: {event_kind}",
                subject=f"my-crew: {event_kind} — {task.title}",
            ))
        except Exception:  # noqa: BLE001 — escalation must never crash the ticker
            logger.exception(
                "team-tick: escalate(%s) failed for task %s (continuing — task state "
                "already updated)", event_kind, task.id,
            )
            return False

    return _escalate
