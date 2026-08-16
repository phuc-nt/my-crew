"""Per-attempt step transcript recorder — pi-style "session" files (v80).

Every team-step attempt gets one append-only JSONL file capturing its full process:
`data_dir/artifacts/team-tasks/<task_id>/transcripts/<step_id>-<attempt_id>.jsonl`.
Events: `meta`, `llm_request`, `llm_response`, `loop_input`, `tool_call`,
`tool_result`, `prefetch`, `outcome` — each line one JSON object with `t`, `seq`, `ts`.

A contextvar carries the recorder so hooks deep in the stack (`LlmClient.complete`,
`community_loop_core`, `collect_prefetch`) record without threading a parameter through
every layer. The worker is a sync single-thread process running exactly ONE step attempt,
so a single contextvar cannot cross-talk; outside a step context `record_event` is a no-op.

Contract: the recorder NEVER breaks the step. Every write error is swallowed (one
warning per recorder, not per event); a transcript is best-effort observation, and a
silent gap is the accepted trade-off for never failing real work. Secret-looking
strings (`sk-…` keys, `Bearer` tokens) are scrubbed at write time.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from collections.abc import Iterator
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

logger = logging.getLogger(__name__)

#: Cap on inlined tool args/results — enough to see WHAT was fetched, not a full dump.
HEAD_CHARS = 2048

#: File name segments (step_id, attempt_id) — same shape as a task id: one safe path
#: segment, no '/' or '..'. An id that fails this simply disables recording (no-op),
#: it never raises into the step.
_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
)


def scrub_secrets(text: str) -> str:
    """Replace secret-looking substrings with a redaction marker."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def head(text: Any, limit: int = HEAD_CHARS) -> str:
    """First `limit` chars of `text` (stringified), marking truncation."""
    s = str(text)
    if len(s) <= limit:
        return s
    return s[:limit] + f"…[+{len(s) - limit} chars]"


def transcripts_dir(data_dir: Path, task_id: str) -> Path:
    """`data_dir/artifacts/team-tasks/<task_id>/transcripts/` — path-confined via
    `task_artifact_dir` (validates task_id, same traversal guard as artifacts)."""
    from my_crew.agent.team_task_artifact import task_artifact_dir

    return task_artifact_dir(data_dir, task_id) / "transcripts"


def step_transcript_path(data_dir: Path, task_id: str, step_id: str, attempt_id: str) -> Path:
    """The one transcript file for a (step, attempt). Raises ValueError on unsafe ids —
    callers that must not fail (the recorder itself) catch it; consumers (review
    evidence) want the loud error."""
    for segment in (step_id, attempt_id):
        if not _SEGMENT_RE.match(segment):
            raise ValueError(f"unsafe transcript path segment: {segment!r}")
    return transcripts_dir(data_dir, task_id) / f"{step_id}-{attempt_id}.jsonl"


#: v80 P4: the ONLY fields an `on_activity` event may carry — a hard-coded identifier/
#: count allowlist, not a body filter. There is no code path by which tool args, tool
#: results, or LLM content reach the callback (PII invariant #3 holds by construction).
ACTIVITY_FIELDS = ("agent", "task", "step", "tool", "count", "phase")

#: Closed activity-phase vocabulary: "calling-tool" (a tool/prefetch fired) or
#: "writing" (an LLM request went out — the model is producing text).
ACTIVITY_PHASES = ("calling-tool", "writing")


class StepRecorder:
    """Appends scrubbed JSON lines to one transcript file. All errors swallowed.

    `on_activity` (v80 P4, optional): called once per tool_call/prefetch/llm_request
    event with an allowlisted `{agent, task, step, tool, count, phase}` dict — the live
    "đang làm gì" signal for the office feed. Same never-break contract as the
    transcript itself: a raising callback is swallowed (one warning)."""

    def __init__(
        self, path: Path, fh: IO[str], *, on_activity: Any = None,
        agent: str = "", task: str = "", step: str = "",
    ) -> None:
        self._path = path
        self._fh: IO[str] | None = fh
        self._seq = 0
        self._warned = False
        self._on_activity = on_activity
        self._agent = agent
        self._task = task
        self._step = step
        self._tool_count = 0
        self._activity_warned = False

    def _emit_activity(self, event: dict[str, Any]) -> None:
        if self._on_activity is None:
            return
        kind = event.get("t")
        if kind == "tool_call":
            self._tool_count += 1
            tool, phase = str(event.get("name") or ""), "calling-tool"
        elif kind == "prefetch":
            self._tool_count += 1
            tool, phase = "web-prefetch", "calling-tool"
        elif kind == "llm_request":
            tool, phase = "", "writing"
        else:
            return
        try:
            self._on_activity({
                "agent": self._agent, "task": self._task, "step": self._step,
                "tool": tool, "count": self._tool_count, "phase": phase,
            })
        except Exception:  # noqa: BLE001 — the feed must never break the step
            if not self._activity_warned:
                self._activity_warned = True
                logger.warning("step activity callback failed for %s (further errors "
                               "silenced)", self._path, exc_info=True)

    def record(self, event: dict[str, Any]) -> None:
        self._emit_activity(event)
        if self._fh is None:
            return
        try:
            payload = dict(event)
            payload["seq"] = self._seq
            payload["ts"] = datetime.now(UTC).isoformat()
            line = json.dumps(payload, ensure_ascii=False, default=str)
            self._fh.write(scrub_secrets(line) + "\n")
            self._fh.flush()
            self._seq += 1
        except Exception:  # noqa: BLE001 — observation must never break the step
            if not self._warned:
                self._warned = True
                logger.warning("step transcript write failed for %s (further errors "
                               "silenced)", self._path, exc_info=True)

    def close(self) -> None:
        if self._fh is not None:
            with contextlib.suppress(Exception):
                self._fh.close()
            self._fh = None


_current_recorder: ContextVar[StepRecorder | None] = ContextVar(
    "step_recorder", default=None
)


def record_event(event: dict[str, Any]) -> None:
    """Record one event into the active step transcript; no-op outside a step context."""
    recorder = _current_recorder.get()
    if recorder is not None:
        recorder.record(event)


@contextlib.contextmanager
def open_step_recorder(
    settings: Any, *, agent_id: str, task_id: str, step_id: str, attempt_id: str,
    on_activity: Any = None,
) -> Iterator[StepRecorder | None]:
    """Open the attempt's transcript for the duration of the block and install it as
    the process-wide current recorder. Yields None (and records nothing) when
    `settings.step_transcripts` is off or the file cannot be opened."""
    if not getattr(settings, "step_transcripts", True):
        yield None
        return
    recorder: StepRecorder | None = None
    try:
        path = step_transcript_path(
            Path(getattr(settings, "data_dir", "")), task_id, step_id, attempt_id
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        recorder = StepRecorder(
            path, path.open("a", encoding="utf-8"), on_activity=on_activity,
            agent=agent_id, task=task_id, step=step_id,
        )
    except Exception:  # noqa: BLE001 — a failed open degrades to no transcript
        logger.warning("step transcript open failed for %s/%s attempt %s (step runs "
                       "without transcript)", task_id, step_id, attempt_id, exc_info=True)
        yield None
        return
    token = _current_recorder.set(recorder)
    try:
        recorder.record({
            "t": "meta", "agent": agent_id, "task": task_id,
            "step": step_id, "attempt": attempt_id,
        })
        yield recorder
    finally:
        _current_recorder.reset(token)
        recorder.close()
