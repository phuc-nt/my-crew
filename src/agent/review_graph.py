"""Peer-review execution graph: `perceive_locked → review → deliver` (M32).

Runs ONE review-step, on the REVIEWER's persona, as the SAME `team-step` generic run
kind every content step runs as (`team_step_runner._run_graph` dispatches here when
`step.step_type == "review"` — see that module). A review-step is minted by the ticker
rule (`coordinator_nodes.tick_actions`) AFTER a content ("work") step with
`needs_review=True` reaches `done`; this graph is what the reviewer's spawned worker
actually executes.

  - `perceive_locked`: reads the REVIEWED step's handoff artifact — round 0 reviews the
    ORIGINAL content step's artifact; round >=1 reviews the LATEST rework's artifact
    instead (each rework writes its own `step-<rework_seq>.json`, a fresh seq, not an
    overwrite of the content step's own) — `graded_seq` (NOT `verdict_seq`, see
    `ReviewStepInput`'s field docs) is which of the two this run reads. Verifies the
    artifact's `version` field equals the `locked_version` this review-step was minted
    with (the graded step's DONE-attempt `attempt_id`, see `review_insert
    ._insert_review_step`) — an EQUALITY check, not "latest". A mismatch means the
    graded step re-ran (a fresh attempt) AFTER this review was queued — the artifact
    this reviewer would grade is stale. Signaled as a `"stale_artifact"` result (never
    raised past `run_review_step`); the ticker reads that and re-queues a FRESH
    review-step against the new version instead of ever completing a review against
    content nobody will ever see again.
  - `review`: one structured LLM call (`llm.team_task_prompt.build_review_messages`,
    the SAME failures-first criteria-anchored rubric `team_task_check_prompt`'s
    self_check uses) grading the artifact's `result_text` against the REVIEWED step's
    own `acceptance` column (the rubric is the content step's, not the review-step's
    own — a review-step never carries its own `acceptance`). Returns a `ReviewVerdict`
    {passed, failures} — binary, no steering surface (see module docstring below).
  - `deliver`: writes the verdict artifact `step-<n>-review-<round>.json` (round baked
    into the FILENAME so a round-2 re-review never clobbers round-1's verdict, see
    `team_task_artifact.write_review_verdict_artifact`) and returns a short room-message
    line. The ticker (`coordinator_nodes.review_insert`) is the ONLY reader of this
    artifact and the ONLY place a rework/re-review row is ever inserted — this graph's
    output is data, never an instruction to the coordinator.

    The verdict artifact ALSO carries a `result_text` field — "prior output + STRUCTURED
    failures", the exact shape a rework-step's brief needs (phase Implementation Step 6)
    — so a ticker-minted rework-step (`deps=[review_step_id]`) can carry that brief
    through the EXISTING generic `team_task_graph._read_deps_handoff` mechanism (which
    this module must never reach into directly — P1/P3 own that graph) instead of
    stuffing it into a title. `format_internal_content` wrapping happens downstream,
    exactly once, when the rework step's own `perceive`→`work` turns this artifact's
    `result_text` into `handoff_context` (`team_task_prompt.build_team_step_messages`
    already wraps `handoff_context` before it reaches any prompt) — this module writes
    plain text to a local JSON file, never a prompt, so no wrap is needed here.

Anti-steering (M32 red line, Decision D): `ReviewVerdict` has exactly two fields
(`passed`, `failures`) — nothing here can change `assigned_to` or request a step outside
the ticker's own rule. `review`'s prompt (`build_review_messages`) explicitly tells the
model its only output channel is this verdict shape.

This graph is deliberately NOT a `StateGraph`/LangGraph build like `team_task_graph.py`:
it is three sequential Python calls with one early-exit (stale artifact) — no branching,
no loop, nothing LangGraph's node/edge machinery would earn its keep for. Kept a plain
function so `team_step_runner` can call it exactly like it calls `_run_graph`, just
without paying for a graph object neither node needs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from src.config.settings import Settings

logger = logging.getLogger(__name__)


class ReviewVerdict(BaseModel):
    """The review LLM call's parsed judgment — binary + failures-first, exactly two
    fields (no steering surface: nothing here can change `assigned_to` or insert a
    step; only the ticker rule, in CODE, ever does that)."""

    passed: bool
    failures: list[str] = Field(default_factory=list)


class ReviewVerdictError(ValueError):
    """Raised by `parse_review_verdict` on malformed JSON/schema — mirrors
    `team_task_check_prompt.CheckVerdictError`'s convention."""


class StaleArtifactError(RuntimeError):
    """Raised by `run_review_step` when the reviewed artifact's `version` no longer
    equals this review-step's locked version — the content step re-ran since this
    review was queued. Mapped to a `"stale_artifact"` result the ticker re-queues a
    fresh review against."""


def parse_review_verdict(raw_json: str) -> ReviewVerdict:
    try:
        doc = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ReviewVerdictError(f"soát chéo không trả về JSON hợp lệ: {exc}") from None
    if not isinstance(doc, dict):
        raise ReviewVerdictError("soát chéo phải là một object JSON")
    try:
        return ReviewVerdict.model_validate(doc)
    except Exception as exc:  # noqa: BLE001 — pydantic ValidationError, wrapped uniformly
        raise ReviewVerdictError(f"soát chéo không hợp lệ: {exc}") from None


@dataclass
class ReviewStepInput:
    """Everything `run_review_step` needs about the review-step + the step it reviews —
    assembled by the caller (`team_step_runner._run_review`) from the store, kept a
    plain dataclass (not the ORM row) so this graph never depends on the store module
    directly.

    Two DIFFERENT seqs matter here, deliberately kept as separate fields so a caller
    can never accidentally conflate them:
      - `graded_seq`: whose artifact this run READS — the ORIGINAL content step's seq
        for round 0, or the LATEST rework step's own seq for round >=1 (a rework writes
        its output to ITS OWN `step-<seq>.json`, a fresh file, never overwriting the
        content step's).
      - `verdict_seq`: the seq baked into the WRITTEN verdict artifact's filename
        (`step-<verdict_seq>-review-<round>.json`) — always the ORIGINAL content step's
        seq, every round, per the phase spec's naming (`<n>` = the reviewed CONTENT
        step, not whichever rework produced round N's input) so every round's verdict
        for the same content step groups under the same `<n>` prefix.
    """

    task_id: str
    graded_seq: int  # artifact seq to READ (content step for round 0, rework for >=1)
    verdict_seq: int  # artifact seq baked into the WRITTEN verdict filename (content step, always)
    review_round: int
    locked_version: str  # graded step's DONE-attempt `attempt_id` (artifact `version`)
    acceptance: str  # the CONTENT step's acceptance criteria (rubric) — never a review/rework row's
    step_title: str = ""  # the CONTENT step's title, for the room message


def run_review_step(
    loaded: Any, settings: Settings, *, data_dir: Any, review_input: ReviewStepInput,
) -> dict:
    """Run one review-step to completion. Returns
    `{status, cost_usd, delivered, room_message, passed, failures}` — `status` and
    `cost_usd`/`delivered`/`room_message` mirror `run_team_step`'s result shape so
    `team_step_runner` can treat both uniformly.

    `status`: `"done"` (verdict artifact written) | `"stale_artifact"` (the reviewed
    content re-ran since this review was queued — no artifact written, the ticker must
    re-queue a fresh review). A stale artifact is an expected, HANDLED outcome (never
    raised past this function) — a genuine LLM/IO error still propagates so the
    caller's normal failed-step handling applies.
    """
    from src.agent.team_task_artifact import read_step_artifact, write_review_verdict_artifact
    from src.company_docs.pool import load_company_docs
    from src.llm.client import LlmClient
    from src.llm.team_task_prompt import build_review_messages
    from src.memory.provider import resolve_memory_text
    from src.profile.context import EMPTY, ProfileContext
    from src.skills.skill_pool import build_skill_context

    artifact = read_step_artifact(data_dir, review_input.task_id, review_input.graded_seq)
    if artifact is None or _artifact_version(artifact) != review_input.locked_version:
        logger.info(
            "review-step %s/seq=%s: stale artifact (locked=%r, found=%r) — signaling "
            "re-review", review_input.task_id, review_input.graded_seq,
            review_input.locked_version, _artifact_version(artifact) if artifact else None,
        )
        return {"status": "stale_artifact", "cost_usd": None, "delivered": False,
                "room_message": "", "passed": None, "failures": []}

    result_text = str(artifact.get("result_text", ""))

    if loaded is not None:
        skills, selector = build_skill_context(loaded, settings)
        context = ProfileContext(
            persona=loaded.soul, project=loaded.project, memory=resolve_memory_text(loaded),
            skills=skills, skill_selector=selector,
            company_docs=load_company_docs(getattr(loaded, "company_docs", ())),
        )
    else:
        context = EMPTY

    llm = LlmClient(settings)
    result = llm.complete(
        build_review_messages(
            result_text=result_text, acceptance=review_input.acceptance, persona=context.persona,
        )
    )
    verdict = parse_review_verdict(result.content)

    write_review_verdict_artifact(
        data_dir, review_input.task_id, review_input.verdict_seq, review_input.review_round,
        {
            "passed": verdict.passed, "failures": list(verdict.failures),
            "reviewed_version": review_input.locked_version, "round": review_input.review_round,
            "result_text": _rework_handoff_text(result_text, verdict.failures),
        },
    )
    verdict_label = "đạt" if verdict.passed else f"cần sửa ({len(verdict.failures)} lỗi)"
    room_message = f"Soát chéo [{review_input.step_title}]: {verdict_label}"
    return {
        "status": "done", "cost_usd": result.cost_usd, "delivered": True,
        "room_message": room_message, "passed": verdict.passed, "failures": list(verdict.failures),
    }


def _rework_handoff_text(prior_output: str, failures: list[str]) -> str:
    """"Prior output + STRUCTURED failures" — the exact brief shape a ticker-minted
    rework-step needs (phase Implementation Step 6), pre-formatted here so it can ride
    through the review-step's own verdict artifact as a plain `result_text` field (see
    module docstring). Plain text only — no `format_internal_content` wrap here, since
    this is a local artifact write, not an LLM prompt; the wrap happens exactly once,
    downstream, when the rework step's own `work` node turns this into `handoff_context`.
    """
    failures_text = "\n".join(f"- {f}" for f in failures) if failures else "(không có chi tiết)"
    return f"{prior_output.strip()}\n\nDanh sách lỗi cần sửa:\n{failures_text}"


def _artifact_version(artifact: dict[str, Any] | None) -> str | None:
    if artifact is None:
        return None
    version = artifact.get("version") or artifact.get("attempt")
    return str(version) if version else None
