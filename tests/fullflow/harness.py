"""FullFlowHarness — run the whole product in-process from a chat trigger.

Boundaries doubled (exactly two, everything between them is REAL product code):
  * `LlmClient.complete` — class-level patch onto ScriptedLlm (covers every
    construction site: ops intent, decompose, steps, reviews, QA).
  * `telegram_write.api_call` — the single urllib seam for ALL Bot API traffic;
    capturing here keeps the real gateway (dedup, rate-limit, allowlist,
    truncation) in the loop and collects every outbound message in `outbox`.

Wiring doubled (the process boundary, replayed synchronously):
  * `team_tick_runner._make_spawn_step` — instead of a detached subprocess the
    spawn calls `worker.main(argv)` in-process with the SAME argv the daemon
    builds, then reports a dead pid — exactly what the ticker sees once a real
    step worker exits.
  * `load_profile` / `load_registry` / `load_company` — resolved to the harness
    cast at every import site, so worker re-loads and roster scans see the same
    tiny company.

Every hop appends to `trace`; `write_trace()` dumps the JSONL used to diagnose
a failing scenario.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .cast import (
    ADMIN_ID,
    BOT_TOKEN_ENV,
    CEO_CHAT_ID,
    COORDINATOR_ID,
    make_cast,
    make_company,
    make_registry,
)
from .scripted_llm import LlmRule, ScriptedLlm

#: Fake child pids handed to the ticker — far above any real pid so `pid_alive`
#: reports dead, which is truthful: the synchronous in-process run has finished.
_FAKE_PID_BASE = 10_000_000


def _patch_everywhere(monkeypatch, name: str, original: Any, replacement: Any) -> None:
    """Rebind `name` in EVERY already-imported module holding the original object.

    Product code imports these collaborators both at module top and locally
    inside functions; patching only the source module would miss the top-level
    copies. Matching on object identity keeps the sweep surgical.

    A module imported MID-test (e.g. `worker`, first pulled in by the spawn
    patch) copies the then-active double at its own import time; monkeypatch
    never touched that attribute, so teardown leaves the stale double behind
    for the next test. The `_fullflow_double` marker lets the sweep recognize
    and replace those leftovers too — otherwise test 2's worker silently runs
    with test 1's cast and data dir.
    """
    replacement._fullflow_double = True
    for module in list(sys.modules.values()):
        if module is None:
            continue
        current = getattr(module, name, None)
        if current is original or getattr(current, "_fullflow_double", False):
            monkeypatch.setattr(module, name, replacement, raising=False)


class FullFlowHarness:
    def __init__(
        self,
        tmp_path: Path,
        monkeypatch,
        *,
        rules: list[LlmRule] | None = None,
        autopilot: bool = False,
        auto_confirm: bool = False,
    ):
        self.data_dir = tmp_path / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.trace_path = tmp_path / "fullflow-trace.jsonl"
        self.trace: list[dict[str, Any]] = []
        self.outbox: list[dict[str, Any]] = []
        self.llm = ScriptedLlm(rules or [], self._trace)
        self._ts_seq = 0
        self._pid_seq = _FAKE_PID_BASE
        self._sent_message_id = 5000

        self.cast = make_cast(self.data_dir)
        self.company = make_company(autopilot=autopilot, auto_confirm=auto_confirm)
        self._install(monkeypatch)

    # ------------------------------------------------------------------ wiring

    def _install(self, monkeypatch) -> None:
        monkeypatch.setenv(BOT_TOKEN_ENV, "scripted-token")
        monkeypatch.setenv("OPENROUTER_API_KEY", "scripted-key")

        # Path isolation: every store/artifact/log the product opens routes here.
        import my_crew.runtime.agent_paths as agent_paths
        import my_crew.runtime.team_task_paths as team_task_paths

        monkeypatch.setattr(team_task_paths, "DATA_DIR", self.data_dir)
        monkeypatch.setattr(agent_paths, "DATA_DIR", self.data_dir)

        # LLM rung: one class-level patch covers every LlmClient() construction.
        from my_crew.llm.client import LlmClient

        scripted = self.llm

        def _complete(_self, messages, *, model=None, role=None):
            return scripted.complete(messages, model=model, role=role)

        monkeypatch.setattr(LlmClient, "complete", _complete)

        # Same class-level patch for the thin loop's tool-capable seam (v86).
        def _complete_with_tools(_self, messages, tools, *, model=None, role=None):
            return scripted.complete_with_tools(messages, tools, model=model, role=role)

        monkeypatch.setattr(LlmClient, "complete_with_tools", _complete_with_tools)

        # Telegram HTTP seam: capture instead of urllib; gateway logic stays real.
        import my_crew.actions.telegram_write as telegram_write

        def _api_call(token, method, payload=None, *, timeout_s=30):
            entry = {"method": method, "payload": payload or {}}
            self.outbox.append(entry)
            self._trace(
                "telegram_api", method=method,
                chat_id=str((payload or {}).get("chat_id", "")),
                text_head=str((payload or {}).get("text", ""))[:200],
            )
            if method == "sendMessage":
                self._sent_message_id += 1
                return {"message_id": self._sent_message_id}
            return {}

        _patch_everywhere(
            monkeypatch, "api_call", telegram_write.api_call, _api_call
        )

        # Company/registry/profile: the harness cast at every import site.
        import my_crew.profile.loader as profile_loader
        import my_crew.runtime.company as company_mod
        import my_crew.runtime.registry as registry_mod

        company = self.company
        registry = make_registry()
        cast = self.cast

        def _load_company(path=None):
            return company

        def _load_registry(path=None):
            return registry

        def _load_profile(agent_id, *, data_dir=None, **_kw):
            try:
                return cast[agent_id]
            except KeyError:
                raise FileNotFoundError(
                    f"fullflow cast has no agent {agent_id!r}"
                ) from None

        _patch_everywhere(
            monkeypatch, "load_company", company_mod.load_company, _load_company
        )
        _patch_everywhere(
            monkeypatch, "load_registry", registry_mod.load_registry, _load_registry
        )
        _patch_everywhere(
            monkeypatch, "load_profile", profile_loader.load_profile, _load_profile
        )

        # Spawn seam: the daemon's detached Popen becomes a synchronous
        # worker.main() with the same argv (minus the interpreter prefix).
        import my_crew.runtime.team_tick_runner as tick_mod

        harness = self

        def _make_spawn_step():
            def _spawn(task, step, attempt_id):
                argv = [
                    "--agent-id", step.assigned_to, "--report", "team-step",
                    "--audience", "internal", "--task-id", task.id,
                    "--step-id", step.step_id, "--attempt-id", attempt_id,
                ]
                harness._trace(
                    "spawn_step", task_id=task.id, step_id=step.step_id,
                    assigned_to=step.assigned_to, attempt_id=attempt_id,
                )
                from my_crew.runtime import worker

                rc = worker.main(argv)
                harness._trace(
                    "step_worker_exit", task_id=task.id, step_id=step.step_id,
                    returncode=rc,
                )
                harness._pid_seq += 1
                return harness._pid_seq

            return _spawn

        monkeypatch.setattr(tick_mod, "_make_spawn_step", _make_spawn_step)

    # ------------------------------------------------------------------ trace

    def _trace(self, event: str, **fields: Any) -> None:
        self.trace.append({"event": event, **fields})

    def write_trace(self) -> Path:
        with self.trace_path.open("w", encoding="utf-8") as fh:
            for row in self.trace:
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        return self.trace_path

    # ---------------------------------------------------------------- actions

    def trigger(self, text: str, *, user: str | None = None,
                ts: str | None = None) -> str:
        """One CEO chat message through the REAL intake seam (`answer_mention`).

        Returns the text of the newest outbound Telegram message (the reply the
        CEO would see), "" when the turn produced no send.
        """
        from my_crew.agent.qa_answer import answer_mention

        self._ts_seq += 1
        mention = {
            # `ts` override lets a scenario REPLAY the same message (poll overlap)
            # to prove the intake dedup claim drops it.
            "ts": ts or f"tg:{CEO_CHAT_ID}:{self._ts_seq}",
            "text": text,
            "channel": CEO_CHAT_ID,
            "user": user or CEO_CHAT_ID,
            "transport": "telegram",
            "message_id": self._ts_seq,
            "chat_type": "private",
            "update_id": self._ts_seq,
        }
        self._trace("trigger", text=text, ts=mention["ts"])
        before = len(self.outbox)
        admin = self.cast[ADMIN_ID]
        answer_mention(admin, admin.settings, mention=mention)
        reply = self.last_message_text(since=before)
        self._trace("trigger_reply", reply_head=reply[:200])
        return reply

    def pump(self, ticks: int = 1) -> None:
        """Replay the daemon's cadence: team-tick (coordinator) then
        milestone-mirror (admin), `ticks` times. Steps run synchronously inside
        the tick via the spawn patch, so one pump advances every dispatchable
        step exactly like one minute of daemon time."""
        from my_crew.runtime.milestone_mirror_runner import run_milestone_mirror
        from my_crew.runtime.team_tick_runner import run_team_tick

        coordinator = self.cast[COORDINATOR_ID]
        admin = self.cast[ADMIN_ID]
        for i in range(ticks):
            self._trace("tick", n=i + 1)
            result = run_team_tick(coordinator, coordinator.settings)
            self._trace("tick_result", **{k: str(v) for k, v in (result or {}).items()})
            run_milestone_mirror(admin, admin.settings)
        self.snapshot_tasks()

    def answer_clarify(self, answer: str, *, clarify_id: int | None = None) -> int:
        """Answer the newest pending clarify via the REAL button path."""
        from my_crew.runtime.clarify_service import apply_answer
        from my_crew.runtime.clarify_store import ClarifyStore
        from my_crew.runtime.team_task_paths import clarify_db_path

        if clarify_id is None:
            store = ClarifyStore(clarify_db_path())
            try:
                pending = store.list_pending()
            finally:
                store.close()
            assert pending, "answer_clarify: no pending clarification"
            clarify_id = pending[-1].id
        ok = apply_answer(clarify_id, answer)
        self._trace("clarify_answer", clarify_id=clarify_id, answer=answer, applied=ok)
        assert ok, f"apply_answer({clarify_id}) returned False"
        return clarify_id

    # ------------------------------------------------------------- inspection

    def last_message_text(self, *, since: int = 0) -> str:
        for entry in reversed(self.outbox[since:]):
            if entry["method"] == "sendMessage":
                return str(entry["payload"].get("text", ""))
        return ""

    def sent_texts(self) -> list[str]:
        return [
            str(e["payload"].get("text", ""))
            for e in self.outbox
            if e["method"] == "sendMessage"
        ]

    def store(self):
        from my_crew.runtime.team_task_paths import team_tasks_db_path
        from my_crew.runtime.team_task_store import TeamTaskStore

        return TeamTaskStore(team_tasks_db_path())

    def task_rows(self) -> list[dict[str, Any]]:
        store = self.store()
        try:
            rows = store._conn.execute(
                "SELECT id, status, delivery_status, reopen_count, autopilot_attempts "
                "FROM team_tasks ORDER BY created_at"
            ).fetchall()
        finally:
            store.close()
        keys = ("id", "status", "delivery_status", "reopen_count", "autopilot_attempts")
        return [dict(zip(keys, r, strict=True)) for r in rows]

    def step_rows(self, task_id: str) -> list[dict[str, Any]]:
        store = self.store()
        try:
            rows = store._conn.execute(
                "SELECT step_id, step_type, status, assigned_to FROM team_steps "
                "WHERE task_id = ? ORDER BY seq", (task_id,)
            ).fetchall()
        finally:
            store.close()
        keys = ("step_id", "step_type", "status", "assigned_to")
        return [dict(zip(keys, r, strict=True)) for r in rows]

    def snapshot_tasks(self) -> None:
        try:
            self._trace("tasks_snapshot", tasks=self.task_rows())
        except Exception as exc:  # noqa: BLE001 — snapshot must never mask the test
            self._trace("tasks_snapshot_error", error=str(exc))
