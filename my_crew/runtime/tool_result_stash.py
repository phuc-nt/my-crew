"""Oversized tool results: keep the whole thing on disk, hand the loop a placeholder.

`data_dir/artifacts/team-tasks/<task_id>/tool-results/<step_id>-<n>-<tool>.txt`, a
sibling of `transcripts/` and `work-orders/` and confined the same way (`task_artifact_dir`).

Why a stash rather than a plain trim. A tool with no cap of its own — `history_search`,
`openalex`, the issue-tracker readers — can return tens of thousands of characters, and
`thin_tool_loop` feeds that verbatim into `messages`, where it is re-sent on EVERY
subsequent round. One large result therefore costs its size times the rounds that follow
it. Trimming alone would fix the cost and lose the data; stashing fixes the cost and
keeps the data addressable, which is what makes a later "read the rest" tool possible
without re-running the fetch.

The placeholder is deliberately NOT silent (the `content_caps` rule): it states the true
size and where the full text went, so the model treats a preview as a preview instead of
concluding from a cut-off list as if it were complete.

Same contract as the recorder and the work-order: writing must never break the step. If
the disk write fails the caller still gets a correct, self-describing placeholder — the
data is lost but the loop is not, and a lost stash is strictly better than a dead step.
"""

from __future__ import annotations

import logging
from pathlib import Path

from my_crew.runtime.step_recorder import _SEGMENT_RE, scrub_secrets

logger = logging.getLogger(__name__)

#: Above this many characters a tool result is stashed instead of inlined. Sits between
#: `TOOL_RESULT_CHARS` (6000, what a single capped tool returns) and the transcript's
#: `HEAD_CHARS`, so a tool that already caps itself never trips this path.
TOOL_RESULT_STASH_CHARS = 12_000

#: How much of the head survives into the prompt. Enough to judge whether the result is
#: on-topic and worth retrieving, not enough to re-inflate the context.
STASH_PREVIEW_CHARS = 2_000


def tool_results_dir(data_dir: Path, task_id: str) -> Path:
    """`data_dir/artifacts/team-tasks/<task_id>/tool-results/` — path-confined via
    `task_artifact_dir`, exactly like the sibling `transcripts/` dir."""
    from my_crew.agent.team_task_artifact import task_artifact_dir

    return task_artifact_dir(data_dir, task_id) / "tool-results"


def stash_path(data_dir: Path, task_id: str, artifact_id: str) -> Path:
    """The one file for a stashed result. Raises ValueError on an unsafe id."""
    if not _SEGMENT_RE.match(artifact_id):
        raise ValueError(f"unsafe stash path segment: {artifact_id!r}")
    return tool_results_dir(data_dir, task_id) / f"{artifact_id}.txt"


def _artifact_id(step_id: str, iteration: int, tool_name: str, seq: int) -> str:
    """A stable, filesystem-safe name for one stashed result.

    Carries the round and a per-round sequence because one round may call the same tool
    several times, and two results overwriting each other would silently destroy the
    evidence the stash exists to keep.
    """
    step = step_id if _SEGMENT_RE.match(step_id or "") else "nostep"
    tool = tool_name if _SEGMENT_RE.match(tool_name or "") else "tool"
    return f"{step}-r{max(iteration, -1)}-{tool}-{seq}"


def _placeholder(text: str, artifact_id: str, written: bool) -> str:
    preview = text[:STASH_PREVIEW_CHARS]
    where = (
        f"bản đầy đủ ở artifact tool-results/{artifact_id}.txt"
        if written
        else "KHÔNG lưu được bản đầy đủ (lỗi ghi đĩa)"
    )
    return (
        f"{preview}\n"
        f"…[kết quả dài {len(text)} ký tự, đang hiển thị {len(preview)} ký tự đầu — "
        f"{where}. Nếu cần phần chưa hiển thị, hãy gọi lại công cụ với truy vấn hẹp hơn.]"
    )


def stash_if_oversized(text: str, tool_name: str, seq: int = 0) -> str:
    """`text` unchanged when it fits; otherwise the full text to disk and a placeholder back.

    Reads the run's identity from the ambient tool-call context rather than parameters:
    the toolset is bound before the loop starts, so there is no argument to thread through
    (see `tool_call_context`). Without a task id there is nowhere confined to write, so the
    text is still previewed — bounding the context is the half that must work everywhere.
    """
    if len(text) <= TOOL_RESULT_STASH_CHARS:
        return text

    from my_crew.runtime_backends.tool_call_context import current_tool_call_context

    ctx = current_tool_call_context()
    artifact_id = _artifact_id(ctx.step_id, ctx.iteration, tool_name, seq)
    written = False
    if ctx.task_id:
        try:
            from my_crew.runtime.team_task_paths import team_tasks_root

            path = stash_path(team_tasks_root(), ctx.task_id, artifact_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(scrub_secrets(text), encoding="utf-8")
            written = True
        except (OSError, ValueError):
            logger.warning("could not stash oversized %s result", tool_name, exc_info=True)
    return _placeholder(text, artifact_id, written)
