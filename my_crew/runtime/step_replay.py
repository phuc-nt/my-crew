"""Re-run one recorded team-step attempt from its frozen work-order (v80 P2).

Replay is a RE-RUN of the tier pipeline, NOT a verbatim playback: the work-order froze
the step-level input (handoff, acceptance, runtime kind, model chains), but persona,
MEMORY.md, skills, and the model itself may have drifted since the original attempt.
Compare trends, not bytes — the verbatim messages of the original run live in the
transcript (`transcripts/<step>-<attempt>.jsonl`) for manual diffing.

Isolation model: the whole re-run happens inside a THROWAWAY sandbox data_dir
(a tempdir holding its own `team_tasks.sqlite3` + the frozen handoff materialized as a
dep artifact). The real store is only ever READ (work-order + original artifact for the
diff) — replay adds no write path to production data. Network is off by default: the
search hook and the sprint prefetch are stubbed with `REPLAY_NET_OFF`, so a needs_web
step sees an explicit "no data" marker instead of silently re-fetching the live web.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from my_crew.runtime.step_work_order import load_work_order

logger = logging.getLogger(__name__)

#: What a replayed step's search/prefetch hooks return instead of live web data.
REPLAY_NET_OFF = (
    "REPLAY: network off — dữ liệu web không được tải lại khi replay; "
    "kết quả chỉ dựa trên handoff đã đóng băng."
)

#: step_id of the synthetic dep row carrying the frozen handoff in the sandbox.
_DEP_STEP_ID = "replay-dep"


def replay_step(
    loaded: Any,
    settings: Any,
    *,
    task_id: str,
    step_id: str,
    attempt_id: str | None = None,
    model: str | None = None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """Re-run one step attempt from its work-order. Returns
    `{result_text, cost_usd, diff_summary, effective_kind, work_order}`.

    Raises FileNotFoundError (no work-order), ValueError (review step / unsafe ids),
    or RuntimeError (tier failures) — the CLI maps all three to exit 1.
    """
    if data_dir is None:
        from my_crew.runtime.team_task_paths import team_tasks_root

        data_dir = team_tasks_root()
    data_dir = Path(data_dir)
    order = load_work_order(data_dir, task_id, step_id, attempt_id=attempt_id)
    if str(order.get("step_type") or "work") == "review":
        raise ValueError(
            "step-replay chưa hỗ trợ bước review — phiên bản artifact được chấm khi đó "
            "không tái tạo được; đối chiếu bằng transcript của attempt review."
        )
    if model:
        # One explicit chain for EVERY role: the operator asked to re-run on model X,
        # so role overrides from the current profile must not silently win.
        settings = dataclasses.replace(
            settings, openrouter_model=model, model_chain=(model,), role_models=(),
        )

    sandbox = Path(tempfile.mkdtemp(prefix="my-crew-step-replay-"))
    try:
        step = _materialize_sandbox(sandbox, order)
        result_text, cost_usd, effective_kind = _run_tier(
            loaded, settings, sandbox=sandbox, order=order, step=step
        )
        diff_summary = _diff_vs_original(data_dir, order, result_text)
        return {
            "result_text": result_text,
            "cost_usd": cost_usd,
            "diff_summary": diff_summary,
            "effective_kind": effective_kind,
            "work_order": order,
        }
    finally:
        with contextlib.suppress(Exception):
            shutil.rmtree(sandbox)


def _materialize_sandbox(sandbox: Path, order: dict[str, Any]) -> Any:
    """Build a minimal sandbox store: the task row (frozen brief) + one synthetic dep
    row whose artifact IS the frozen handoff + the replayed step row itself. The graph
    then runs its REAL perceive path (deps-aware handoff read) against frozen data."""
    from my_crew.agent.team_task_artifact import write_step_artifact
    from my_crew.runtime.team_task_store import TeamTaskStore

    task_id = str(order["task_id"])
    handoff = str(order.get("handoff") or "")
    store = TeamTaskStore(sandbox / "team_tasks.sqlite3")
    try:
        store.create_task(
            task_id=task_id,
            title=str(order.get("task_title") or task_id),
            original_request=str(order.get("original_request") or ""),
            assigned_by="step-replay",
        )
        deps: list[str] = [_DEP_STEP_ID] if handoff else []
        steps: list[dict[str, Any]] = []
        if handoff:
            steps.append({
                "step_id": _DEP_STEP_ID, "title": "handoff đóng băng (work-order)",
                "assigned_to": str(order.get("assigned_to") or ""), "deps": [],
            })
        steps.append({
            "step_id": str(order["step_id"]),
            "title": str(order.get("step_title") or ""),
            "assigned_to": str(order.get("assigned_to") or ""),
            "deps": deps,
            "acceptance": str(order.get("acceptance") or ""),
            "step_type": str(order.get("step_type") or "work"),
            "needs_shell": bool(order.get("needs_shell")),
            "needs_web": bool(order.get("needs_web")),
        })
        store.set_plan(task_id, steps, plan_hash=str(order.get("plan_hash") or "replay"))
        if handoff:
            dep_row = store.get_step(task_id, _DEP_STEP_ID)
            write_step_artifact(
                sandbox, task_id, dep_row.seq,
                {"status": "done", "result_text": handoff},
            )
        return store.get_step(task_id, str(order["step_id"]))
    finally:
        store.close()


def _run_tier(
    loaded: Any, settings: Any, *, sandbox: Path, order: dict[str, Any], step: Any,
) -> tuple[str, float | None, str]:
    """Resolve the runtime for the (rebuilt) step and run the graph in the sandbox —
    the same build `team_step_runner._run_graph` does, minus every production write:
    no checkpointer, no memory store/remember node, no external_write, no split."""
    from my_crew.company_docs.pool import load_company_docs
    from my_crew.memory.provider import resolve_memory_text
    from my_crew.profile.capability_block import build_capability_block
    from my_crew.profile.context import EMPTY, ProfileContext
    from my_crew.runtime_backends.protocol import resolve_step_runtime
    from my_crew.skills.skill_pool import build_skill_context

    if loaded is not None:
        skills, selector = build_skill_context(loaded, settings)
        context = ProfileContext(
            persona=loaded.soul, project=loaded.project, memory=resolve_memory_text(loaded),
            capability=build_capability_block(loaded, None),
            skills=skills, skill_selector=selector,
            company_docs=load_company_docs(getattr(loaded, "company_docs", ())),
        )
    else:
        context = EMPTY

    runtime = resolve_step_runtime(loaded, step, prefetched=False)
    effective_kind = type(runtime).__name__
    frozen_kind = str(order.get("effective_runtime") or "")
    if frozen_kind and frozen_kind != effective_kind:
        logger.warning(
            "step-replay: runtime kind drifted — attempt gốc chạy %s, replay resolve ra %s",
            frozen_kind, effective_kind,
        )

    _extra: dict[str, Any] = {"allow_split": False}
    if loaded is not None and effective_kind != "NativeGraphRuntime":
        _extra["reporting_config"] = loaded.config
        _extra["runtime_config"] = loaded.agent_runtime
        # Network-off replay: every live-web/toolset opt-in stays False regardless of
        # what the profile says today.
        _extra["academic_search"] = False
        _extra["gws_context"] = False
        _extra["web_search"] = False
        _extra["deep_team"] = False
    if str(getattr(step, "step_type", "work") or "work") == "sprint":
        from my_crew.runtime.sprint_runner import build_sprint_work

        # Same gate as the live runner: sprint work already runs its own code-side
        # coverage, so the graph's deterministic self-check pre-check stays off.
        _extra["deterministic_precheck"] = False
        _extra["work_override"] = build_sprint_work(
            loaded=loaded, settings=settings, context=context,
            acceptance=str(getattr(step, "acceptance", "") or ""), telemetry=None,
            prefetch=lambda *_a, **_k: REPLAY_NET_OFF, on_phase=None,
            needs_web=bool(getattr(step, "needs_web", True)),
        )

    graph = runtime.build_task(
        settings=settings, context=context, step_title=step.title,
        data_dir=sandbox, task_id=str(order["task_id"]), step_seq=step.seq,
        step_deps=step.deps,
        search_hook=(
            (lambda _q: REPLAY_NET_OFF) if bool(getattr(step, "needs_web", False)) else None
        ),
        self_id="", telemetry=None, remember_node=None,
        guidance=str(order.get("guidance") or ""), **_extra,
    )
    state: dict[str, Any] = {
        "step_title": step.title, "acceptance": str(getattr(step, "acceptance", "") or ""),
        "attempt_id": "replay", "version": "replay",
    }
    stream_input = dict(state)
    for mode, chunk in graph.stream(stream_input, None, stream_mode=["updates", "custom"]):
        if mode != "updates" or not isinstance(chunk, dict):
            continue
        if "__interrupt__" in chunk:
            # A replay has no CEO to answer — record the pause and stop cleanly.
            state["status"] = "interrupted"
            break
        for node_output in chunk.values():
            if isinstance(node_output, dict):
                state.update(node_output)
    return str(state.get("result_text") or ""), state.get("cost_usd"), effective_kind


def _diff_vs_original(data_dir: Path, order: dict[str, Any], result_text: str) -> str:
    """Coarse drift signal vs the ORIGINAL attempt's artifact: lengths + where the two
    texts first diverge (YAGNI — no smart diff; the point is 'same ballpark or not')."""
    from my_crew.agent.team_task_artifact import read_step_artifact

    artifact = read_step_artifact(
        data_dir, str(order["task_id"]), int(order.get("step_seq") or 0)
    )
    if artifact is None:
        return "artifact gốc không còn (đã bị sweep hoặc chưa từng ghi) — không so được"
    original = str(artifact.get("result_text") or "")
    if original == result_text:
        return f"trùng khớp từng byte ({len(original)} ký tự)"
    diverge = next(
        (i for i, (a, b) in enumerate(zip(original, result_text, strict=False)) if a != b),
        min(len(original), len(result_text)),
    )
    return (
        f"gốc {len(original)} ký tự, replay {len(result_text)} ký tự; "
        f"khác nhau từ vị trí {diverge} "
        f"(gốc: {original[diverge:diverge + 80]!r}… / replay: "
        f"{result_text[diverge:diverge + 80]!r}…)"
    )
