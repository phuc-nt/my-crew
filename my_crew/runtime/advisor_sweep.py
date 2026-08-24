"""Advisor ride-along — a second pair of eyes on steps that are still running.

The working agent judges its own output from inside its own context: it cannot see
that it has been circling the same failing tool for six calls, or that it answered a
different question than the one it was given. This sweep gives that view to someone
else. Every team tick it reads what each running step has NEWLY written to its
transcript, hands that delta to a second model, and lets it either stay silent (the
expected outcome) or leave exactly one short note.

Two channels, chosen by how much the note deserves to cost:

- `nit`     → an office-room note. The CEO and the feed see it; the agent does not
              have to care. This is where "worth mentioning" goes to be cheap.
- `concern` → appended step guidance, which rides into the step's next attempt
              (`team_task_store.append_step_guidance`). This one actually steers work,
              so it is the only severity that touches the store.

Everything else about the design is about NOT being noisy, because an advisor that
cries wolf is worse than no advisor at all:

- silence is the prompted default, and a silent verdict writes nothing anywhere;
- one note per step per sweep, maximum;
- a note that repeats something already said for that step is dropped (normalized
  dedupe keys, kept per step and bounded);
- after emitting, the step is skipped for `COOLDOWN_SWEEPS` sweeps so the agent gets
  room to act before being told anything else;
- unparseable or oversized model output is quarantined — treated as silence, never
  forwarded to the agent as-is.

The sweep never fails the tick. Every outward call is best-effort, the whole body is
guarded by the caller, and a step whose advisor call raises simply keeps its cursor so
the next sweep re-reads the same delta.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Most transcript bytes handed to one advisor call. A step under load writes tens of
#: KB per attempt; the advisor wants the RECENT shape of the work, not the archive, so
#: an oversized delta is tail-trimmed rather than split across calls.
MAX_DELTA_CHARS = 24_000

#: Below this, a delta is not worth a model call — a couple of heartbeat lines say
#: nothing an advisor could act on.
MIN_DELTA_CHARS = 400

#: Sweeps to stay quiet on a step after emitting a note. The agent needs a chance to
#: act on what it was told before hearing anything else.
COOLDOWN_SWEEPS = 3

#: Dedupe keys retained per step (FIFO). Bounds the sidecar for a long-running step
#: while still covering "the advisor said this two notes ago".
MAX_SEEN_KEYS = 32

#: Hard ceiling on the note text an advisor may inject. Anything longer is the model
#: writing an essay instead of a note, and is quarantined.
MAX_NOTE_CHARS = 600

#: Sidecar file, next to the retry sidecar in the team-tasks root.
SIDECAR_NAME = "advisor_cursor.json"

_SEVERITIES = ("silent", "nit", "concern")

_ADVISOR_SYSTEM = """\
You are an ADVISOR watching another AI agent work.

YOU ARE READING A FRAGMENT. What follows is only the most recent slice of a longer \
transcript. Work you cannot see has already happened: earlier steps, earlier research, \
earlier sections of the deliverable, instructions the agent was given. Anything \
"missing" from this fragment is missing from YOUR VIEW, not from the work. NEVER flag \
something as absent because it is not in the fragment.

Speak ONLY when the fragment ITSELF contains the evidence. Concretely, that means one \
of these is visible IN FRONT OF YOU:
- the same action repeated with the same failing result, 3+ times;
- an error or empty result the agent keeps building on as if it succeeded;
- output that contradicts something else inside this same fragment;
- the agent working on a different subject than the step title says.

If none of those is literally visible in the fragment, the answer is "silent".

RULES:
- SILENCE IS THE DEFAULT and the common case. A quiet sweep is a success, not a miss.
- Do not speculate about what the agent should do next. That is the agent's job.
- NEVER judge whether a date is in the future or the data is "too recent to exist".
  Your training cut off before today; the agent's clock and its sources are right and
  you are wrong. Dates are never evidence of anything.
- NEVER question a source's freshness, authority, or completeness. Choosing sources is
  the agent's job, and you cannot see what else it has read.
- NEVER restate what the agent already knows or has already said.
- NEVER give generic advice ("be careful", "check your work", "consider edge cases",
  "should verify", "should confirm the structure").
- One short note. Vietnamese. At most 2 sentences, naming the concrete evidence.

Severity — both require the SAME evidence bar above; "nit" is a softer tone, NOT a
lower standard, so never downgrade a hunch to a nit just to have something to say:
- "silent"  — the default. Nothing in the fragment proves something is wrong.
- "nit"     — worth noting for the record; the agent need not change course.
- "concern" — visible evidence the agent should change course; reaches its next attempt.

Reply with ONLY a JSON object, no prose, no code fence:
{"severity": "silent"} or {"severity": "nit"|"concern", "note": "..."}\
"""


def run_advisor_sweep(
    store: Any, settings: Any, *, llm: Any = None, data_dir: Path | None = None,
) -> int:
    """One sweep over running steps. Returns the number of notes emitted.

    Returns 0 immediately when the advisor or the transcripts it reads are off — the
    tick pays nothing for a fleet that has not opted in.
    """
    if not getattr(settings, "advisor_enabled", False):
        return 0
    if not getattr(settings, "step_transcripts", True):
        return 0

    root = data_dir if data_dir is not None else _team_tasks_root()
    sidecar_path = root / SIDECAR_NAME
    state = _load_sidecar(sidecar_path)
    dirty = False
    emitted = 0

    for step in _running_steps(store):
        key = f"{step['task_id']}/{step['step_id']}"
        entry = state.setdefault(key, {"offset": 0, "cooldown": 0, "seen": []})
        if entry.get("cooldown", 0) > 0:
            entry["cooldown"] = int(entry["cooldown"]) - 1
            dirty = True
            continue

        path = _transcript_path(root, step)
        if path is None:
            continue
        delta, new_offset = _read_delta(path, int(entry.get("offset", 0)))
        if new_offset != entry.get("offset"):
            entry["offset"] = new_offset
            dirty = True
        if len(delta) < MIN_DELTA_CHARS:
            continue

        try:
            verdict = _ask_advisor(delta, step, settings, llm)
        except Exception:  # noqa: BLE001 — one step's advisor never stops the sweep
            logger.warning("advisor: call failed for %s", key, exc_info=True)
            continue
        if verdict is None:
            continue

        severity, note = verdict
        seen_key = _dedupe_key(note)
        if seen_key in entry.get("seen", []):
            continue

        if _emit(step, severity, note, store):
            entry.setdefault("seen", []).append(seen_key)
            entry["seen"] = entry["seen"][-MAX_SEEN_KEYS:]
            entry["cooldown"] = COOLDOWN_SWEEPS
            dirty = True
            emitted += 1

    if dirty:
        _prune(state, store)
        _save_sidecar(sidecar_path, state)
    return emitted


def _team_tasks_root() -> Path:
    from my_crew.runtime.team_task_paths import team_tasks_root

    return team_tasks_root()


def _running_steps(store: Any) -> list[dict]:
    """Steps currently in flight, with the ids their transcript file is named after."""
    rows = store._conn.execute(
        "SELECT task_id, step_id, attempt_id, title, assigned_to FROM team_steps "
        "WHERE status = 'running' AND attempt_id IS NOT NULL AND attempt_id != ''"
    ).fetchall()
    return [
        {"task_id": r[0], "step_id": r[1], "attempt_id": r[2],
         "title": r[3] or "", "assigned_to": r[4] or ""}
        for r in rows
    ]


def _transcript_path(root: Path, step: dict) -> Path | None:
    """Locate the attempt's transcript across every root a worker might have used.

    A step's transcript is written by whichever agent ran it, into THAT agent's own
    data dir (`open_step_recorder` uses the worker's `settings.data_dir`, and a spawned
    worker is jailed to `.data/agents/<id>/`). The shared team-tasks root only holds
    transcripts for steps that ran in-process. So look in the assignee's jail first —
    the overwhelmingly common case — then the shared root, then any other agent's jail,
    which covers a step reassigned between attempts. Same lookup the bench uses
    (`bench/task_metrics._step_transcript_files`); the two must not disagree about
    where a step's transcript lives.
    """
    from my_crew.runtime.step_recorder import step_transcript_path

    agents_dir = root / "agents"
    roots = [root]
    assignee = str(step.get("assigned_to") or "").strip()
    if assignee:
        roots.insert(0, agents_dir / assignee)
    try:
        roots.extend(sorted(d for d in agents_dir.glob("*/") if d not in roots))
    except OSError:
        pass

    for candidate_root in roots:
        try:
            path = step_transcript_path(candidate_root, step["task_id"],
                                        step["step_id"], step["attempt_id"])
        except ValueError:  # unsafe id — the recorder refused to write it either
            return None
        if path.exists():
            return path
    return None


def _read_delta(path: Path, offset: int) -> tuple[str, int]:
    """Text written since `offset`, plus the offset actually consumed.

    Reads to the size captured at open time, so a step writing during the read does not
    make the cursor overshoot: whatever arrives after belongs to the next sweep. A
    shrunken file (a fresh attempt reusing the name) resets the cursor to 0.
    """
    try:
        size = path.stat().st_size
        if size < offset:
            offset = 0
        if size <= offset:
            return "", offset
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(offset)
            text = fh.read(size - offset)
    except OSError:
        return "", offset
    consumed = offset + len(text.encode("utf-8", errors="replace"))
    if len(text) > MAX_DELTA_CHARS:
        text = text[-MAX_DELTA_CHARS:]  # the recent shape, not the archive
    return text, consumed


def _ask_advisor(
    delta: str, step: dict, settings: Any, llm: Any,
) -> tuple[str, str] | None:
    """One advisor call → (severity, note), or None for silence/quarantine."""
    client = llm if llm is not None else _default_client(settings)
    user = (
        f"Bước: {step['title'] or step['step_id']}\n"
        f"Người làm: {step['assigned_to'] or '?'}\n\n"
        f"Transcript mới nhất:\n{delta}"
    )
    result = client.complete(
        [{"role": "system", "content": _ADVISOR_SYSTEM},
         {"role": "user", "content": user}],
        role="advisor",
    )
    return _parse_verdict(getattr(result, "content", "") or "")


def _default_client(settings: Any) -> Any:
    from my_crew.llm.client import LlmClient

    return LlmClient(settings)


def _parse_verdict(raw: str) -> tuple[str, str] | None:
    """Parse the model's JSON verdict. Anything unexpected is quarantined as silence.

    Quarantine rather than salvage: advisor output reaches a working agent's context,
    so text that did not arrive in the agreed shape has not earned that trip.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    severity = str(data.get("severity", "")).strip().lower()
    if severity not in _SEVERITIES or severity == "silent":
        return None
    note = str(data.get("note", "")).strip()
    if not note or len(note) > MAX_NOTE_CHARS:
        return None
    return severity, note


def _dedupe_key(note: str) -> str:
    """Normalized note identity — same point twice does not get said twice."""
    return re.sub(r"[^a-z0-9]+", " ", note.lower()).strip()[:120]


def _emit(step: dict, severity: str, note: str, store: Any) -> bool:
    """Route the note to its channel. True when it actually landed."""
    if severity == "concern":
        try:
            text = f"[advisor] {note}"
            if not store.append_step_guidance(step["task_id"], step["step_id"], text):
                return False
        except Exception:  # noqa: BLE001 — a lost note never breaks the tick
            logger.warning("advisor: guidance write failed for %s/%s",
                           step["task_id"], step["step_id"], exc_info=True)
            return False
        return True
    return _room_note(step, severity, note)


def _room_note(step: dict, severity: str, note: str) -> bool:
    """Best-effort office note — the cheap channel, visible without steering anyone."""
    try:
        from my_crew.runtime.office_room_append import append_office_event, room_for_task

        append_office_event(
            room_for_task(step["task_id"]), author="advisor", kind="advisor",
            body={"task_id": step["task_id"], "step_id": step["step_id"],
                  "step_title": step["title"], "severity": severity, "message": note},
            also_office=True,
        )
    except Exception:  # noqa: BLE001
        logger.warning("advisor: room note failed for %s", step["task_id"], exc_info=True)
        return False
    return True


def _prune(state: dict, store: Any) -> None:
    """Drop sidecar entries for steps that are no longer running — a finished step's
    cursor is dead weight, and its transcript will never grow again."""
    try:
        live = {
            f"{r[0]}/{r[1]}"
            for r in store._conn.execute(
                "SELECT task_id, step_id FROM team_steps WHERE status = 'running'"
            ).fetchall()
        }
    except Exception:  # noqa: BLE001 — pruning is hygiene, never the sweep's fate
        return
    for key in [k for k in state if k not in live]:
        del state[key]


def _load_sidecar(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_sidecar(path: Path, state: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        logger.warning("advisor: sidecar write failed at %s", path, exc_info=True)
