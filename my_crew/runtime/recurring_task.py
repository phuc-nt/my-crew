"""report-task + qa-task check logic (v6 M15b) — recurring work, no natural end.

Unlike a watch-task (M15a) which STOPS when its target closes, a report-task and a qa-task
are open-ended recurring work: "mỗi thứ 6 tổng hợp chi phí gửi tôi", "mỗi sáng: hôm nay ai
quá tải?". They have no "done" state of their own — they run each due tick until the
operator cancels them or the deadline passes (R1: nothing runs forever).

- report-task params: {"kind": <report kind>, "audience": "internal"}. Each run is the
  EXISTING report graph (build_graph_for → invoke) — same delivery, gateway, Lớp B as a
  scheduled report. The task just gives it its own cadence.
- qa-task params: {"question": <text>}. Each run is the M11 Q&A path against the pack's
  primary kind, the answer posted to the agent's channel.

Both cost LLM tokens (a report composes prose, a qa grounds+answers), so the runner tracks
cost per run — unlike watch-task which is a free CODE check.

`run_recurring` performs the whole run (READ + compose + POST through the gateway) and
returns (summary, cost). Deadline is decided by the runner (shared with watch) BEFORE
calling this, so here we only do the work.
"""

from __future__ import annotations

from typing import Any


def run_report_task(task_params: dict[str, Any], loaded, settings) -> tuple[str, float | None]:
    """Run one report-task tick = one scheduled report through the existing graph.

    Reuses `build_graph_for` (the same path cron/worker uses), so delivery, dedup, Lớp B
    for external, and audit all apply unchanged — the task adds a cadence, not a new write
    path. Returns (summary, cost). Cost is None (the graph tracks its own budget spend)."""
    from my_crew.runtime.run_config import invoke_config
    from my_crew.runtime.worker import build_graph_for

    kind = str(task_params.get("kind") or "").strip()
    if not kind:
        raise ValueError("report-task thiếu 'kind'")
    audience = str(task_params.get("audience") or "internal")
    graph = build_graph_for(loaded, settings, kind, audience)
    thread_id = f"task-report:{loaded.profile_id}:{kind}:{audience}"
    graph.invoke({}, config=invoke_config(thread_id, settings))
    return f"Đã chạy báo cáo '{kind}' ({audience}).", None


def run_qa_task(
    task_params: dict[str, Any], loaded, settings, *, gateway,
) -> tuple[str, float | None]:
    """Run one qa-task tick = answer a fixed recurring question with fresh data (M11 path).

    The answer posts to the agent's report channel through the SAME gateway the runner
    already opened. Returns (short summary, cost)."""
    question = str(task_params.get("question") or "").strip()
    if not question:
        raise ValueError("qa-task thiếu 'question'")

    from my_crew.agent.qa_answer import _answer_question
    from my_crew.llm.client import LlmClient
    from my_crew.packs.registry import PackRegistry

    channel = loaded.config.slack_report_channel
    if not channel:
        raise ValueError("agent chưa cấu hình slack_report_channel — không trả lời được")
    pack = PackRegistry().load(loaded.domain)
    # A synthetic mention: qa-task reuses the M11 answer path, which posts a threaded reply.
    # The ts must be STABLE per (agent, question, day) across process restarts, because the
    # M11 reply dedup keys on it (`slack-qa-reply:<channel>:<ts>`). Python's builtin hash()
    # is randomized per process (PYTHONHASHSEED), so it would change every service restart
    # and re-post the same answer — use a deterministic digest instead. The DAY suffix makes
    # it a fresh answer each calendar day (the intended cadence) but at most once per day.
    from datetime import UTC, datetime
    from hashlib import sha256

    digest = sha256(f"{loaded.profile_id}:{question}".encode()).hexdigest()[:12]
    day = datetime.now(UTC).date().isoformat()
    mention = {
        "ts": f"qa-task:{digest}:{day}",
        "text": question, "channel": channel, "user": "task",
        # synthetic ⇒ the reply posts top-level (no fabricated thread_ts into Slack).
        "synthetic": True,
    }
    outcome, cost = _answer_question(
        loaded, settings, mention=mention, pack=pack, gateway=gateway,
        llm=LlmClient(settings), channel=channel,
    )
    return f"Đã trả lời câu hỏi định kỳ (status={outcome.status}).", cost


__all__ = ["run_report_task", "run_qa_task"]
