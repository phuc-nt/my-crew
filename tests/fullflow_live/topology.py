"""Boot a REAL `my-crew serve` process and drive it over a REAL socket.

What this adds over the in-process live suite: those cases import the runtime and call
into it, and the harness replaces the daemon's detached `Popen` with a synchronous
spawn. Useful, but it means the thing under test is not the thing a user runs. Here the
web server and the coordinator are separate OS processes under the real supervisor, the
tick loop is the real loop, and every request crosses a socket — so the seams that only
exist between processes (readiness, auth, concurrent SQLite access, surviving a kill)
are actually exercised.

Isolation rests on one hinge: `MY_CREW_HOME`. It is read at import time in the child,
so everything — profiles, company.yaml, .env, .data/ — must be on disk before boot. The
fixture refuses to run against a home it did not create, because the alternative is a
test that writes into the operator's real fleet.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

from tests.fullflow.cast import ADMIN_ID, COORDINATOR_ID, LIVE_MODEL, LIVE_ROLE_MODELS, WORKERS

#: Boot budget. Generous: the child imports the whole app and seeds a home. A timeout
#: here dumps the server log rather than failing bare, because "did not come up" with no
#: output is the least actionable failure a suite can produce.
BOOT_TIMEOUT_S = 45.0

#: Tick cadence for the child coordinator. The production default is 60s, which would
#: make every journey wait a minute per step; 2s keeps the real loop, just faster.
TEST_TICK_INTERVAL_S = "2"


def _free_port() -> int:
    """A port the OS just confirmed is free. Racy in principle, fine in practice: the
    window between close and the child's bind is microseconds, and the alternative
    (hardcoded port) collides with a developer's own running instance."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


#: Synthetic Telegram operator route for the coordinator.
#:
#: `preview_assign_team_task` hard-blocks delegation unless an escalation could reach
#: the CEO — a real guard (a multi-step task can stall silently), so the fix is to
#: satisfy it, not to loosen the test. This is CONFIG ONLY: the check reads
#: `ops_operator_id ∈ chat_ids` and sends nothing, and the bot token is a placeholder,
#: so no case here ever contacts Telegram. An escalation that genuinely tried to send
#: would fail against these values — which is correct, since the suite must not emit
#: real messages.
_FAKE_OPERATOR_CHAT_ID = "10000001"


def _telegram_block(profile_id: str) -> str:
    if profile_id not in (ADMIN_ID, COORDINATOR_ID):
        return ""
    return (
        "telegram:\n"
        "  bot_token_env: MY_CREW_TEST_TELEGRAM_TOKEN\n"
        f"  ops_operator_id: '{_FAKE_OPERATOR_CHAT_ID}'\n"
        f"  chat_ids: ['{_FAKE_OPERATOR_CHAT_ID}']\n"
        "  poll_minutes: 0\n"
    )


def _tools_tier_block(cost_cap_usd: float | None) -> str:
    """The `agent_runtime:` + tool opt-in lines that move an agent onto the TOOLS tier.

    Measured, and the reason this seam has to exist: with no `agent_runtime:` block a
    profile loads as `kind="native"`, and `resolve_step_runtime` then returns
    `NativeGraphRuntime` for every step — so `thin_tool_loop` and the policy-shimmed read
    toolset, i.e. everything phases 1/3/4/5 changed, never executed ONCE in this suite.
    Cases asserting on them against the default fleet would have been vacuously green.

    NO tool opt-in flag is set here, and `web_search: true` in particular is deliberately
    NOT set: it plus a provider key makes the launcher PREFETCH a `needs_web` step, and a
    non-empty bundle sends the step straight back to the native tier — the opt-in that
    looks most relevant is the one that would silently undo this seam. The tier alone is
    enough to arm a tool: `history.search` is registered unconditionally for internal
    audiences (no flag, no key, no network), so the loop has a real tool on any machine.
    `web.scrape` comes along on its own whenever Firecrawl is configured.

    `cost_cap_usd=None` omits the key entirely, which is the shipped default (no ceiling).
    """
    lines = ["agent_runtime:\n", "  kind: create_agent\n"]
    if cost_cap_usd is not None:
        lines.append(f"  cost_cap_usd: {cost_cap_usd}\n")
    return "".join(lines)


def _write_profile(home: Path, profile_id: str, *, domain: str,
                   gws_context: bool = False,
                   tools_tier: bool = False,
                   cost_cap_usd: float | None = None) -> None:
    """One agent on disk, in the layout the real loader reads.

    Deliberately minimal — the live cast's in-memory profile cannot be handed to another
    process, so this writes the same shape the shipped profiles use. Model pinning lives
    in .env (fleet-wide) so a model swap here stays a one-line change.

    `gws_context` is the per-agent opt-in half of mailbox access; the other half
    (`gws_enabled`) already defaults True in the reporting config, so writing this line
    is what makes an agent mail-capable to `agent_mail_capable`. Default False keeps
    every existing case's fleet exactly as it was — a fleet where NOBODY can read mail,
    which is itself the precondition one of the mail cases needs.

    `tools_tier` / `cost_cap_usd` move the agent onto the tool-calling runtime and give
    it a per-step spend ceiling. Both default off, so a fleet seeded the ordinary way is
    byte-identical to what every pre-existing case has always run against.
    """
    directory = home / "profiles" / profile_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "profile.yaml").write_text(
        f"name: {profile_id}\n"
        "enabled: true\n"
        f"domain: {domain}\n"
        "budget:\n  monthly_usd: 50\n  warn_ratio: 0.8\n"
        # dry_run false: a journey that never really acts proves nothing about the
        # gateway, which is precisely what the adversarial cases measure.
        "safety:\n  dry_run: false\n  write_disabled: false\n"
        "schedule: {}\n"
        "reports: []\n"
        "bindings: {}\n"
        "integrations: {}\n"
        + ("gws_context: true\n" if gws_context else "")
        + (_tools_tier_block(cost_cap_usd) if tools_tier else "")
        + _telegram_block(profile_id),
        encoding="utf-8",
    )
    (directory / "SOUL.md").write_text(
        f"Bạn là {profile_id} trong một công ty agent thử nghiệm.\n", encoding="utf-8"
    )
    (directory / "PROJECT.md").write_text("", encoding="utf-8")
    (directory / "MEMORY.md").write_text("", encoding="utf-8")


def seed_home(home: Path, *, api_key: str, extra_env: dict[str, str] | None = None,
              mail_capable: frozenset[str] | set[str] = frozenset(),
              tools_tier: frozenset[str] | set[str] = frozenset(),
              cost_cap_usd: float | None = None) -> None:
    """Write a complete, self-contained fleet home: profiles, registry, company, .env.

    `mail_capable` names the agents that get `gws_context: true` — i.e. the ones
    `agent_mail_capable` will accept as assignees for a `needs_mail` step. Empty by
    default, so a fleet seeded the ordinary way has no mailbox reader at all.

    `tools_tier` names the agents that run on the tool-calling runtime instead of native,
    and `cost_cap_usd` gives those agents a per-step spend ceiling. Both empty/None by
    default: the ordinary fleet is entirely native and uncapped, exactly as before.
    """
    home.mkdir(parents=True, exist_ok=True)

    def _write(profile_id: str, domain: str) -> None:
        _write_profile(
            home, profile_id, domain=domain,
            gws_context=profile_id in mail_capable,
            tools_tier=profile_id in tools_tier,
            # The ceiling rides with the tier: an agent left on native has no thin loop to
            # enforce it, so writing the key there would look configured and do nothing.
            cost_cap_usd=cost_cap_usd if profile_id in tools_tier else None,
        )

    _write(ADMIN_ID, "admin")
    _write(COORDINATOR_ID, "pm")
    for worker_id, worker_domain in WORKERS:
        _write(worker_id, worker_domain)

    agent_ids = [ADMIN_ID, COORDINATOR_ID, *(w for w, _ in WORKERS)]
    (home / "registry.yaml").write_text(
        "agents:\n" + "".join(f"  - id: {i}\n    enabled: true\n" for i in agent_ids),
        encoding="utf-8",
    )
    (home / "company.yaml").write_text(
        "name: Cty Fullflow Topology\n"
        f"coordinator_id: {COORDINATOR_ID}\n"
        "team_task_cap_usd: 5.0\n"
        "team_task_concurrency: 3\n"
        "team_task_auto_confirm: false\n"
        "autopilot: true\n",
        encoding="utf-8",
    )

    role_models = "\n".join(f"ROLE_MODEL_{k.upper()}={v}" for k, v in LIVE_ROLE_MODELS.items())
    lines = [
        f"OPENROUTER_API_KEY={api_key}",
        f"OPENROUTER_MODEL={LIVE_MODEL}",
        "DRY_RUN=false",
        # Placeholder only — satisfies the config shape the escalation guard reads.
        # Deliberately not a real token: nothing in this suite may message Telegram.
        "MY_CREW_TEST_TELEGRAM_TOKEN=topology-test-not-a-real-token",
        role_models,
    ]
    for key, value in (extra_env or {}).items():
        lines.append(f"{key}={value}")
    (home / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")


@dataclass
class ServeProcess:
    """A running fleet: base URL, the home it owns, and the process handle."""

    base_url: str
    home: Path
    proc: subprocess.Popen
    log_path: Path
    _jar: CookieJar = field(default_factory=CookieJar)

    # -- HTTP (stdlib urllib, matching the repo's no-new-dependency convention) ------

    def _opener(self):
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar))

    def request(self, method: str, path: str, payload: Any = None,
                *, timeout: float = 30.0) -> tuple[int, Any]:
        """(status, parsed-or-text). Never raises on HTTP status — a 401/409 is a
        result these cases assert on, not an exception to wrap at every call site."""
        url = f"{self.base_url}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
        try:
            with self._opener().open(req, timeout=timeout) as resp:
                return resp.status, _decode(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, _decode(exc.read())

    def get(self, path: str, **kw) -> tuple[int, Any]:
        return self.request("GET", path, **kw)

    def post(self, path: str, payload: Any = None, **kw) -> tuple[int, Any]:
        return self.request("POST", path, payload, **kw)

    # -- lifecycle -------------------------------------------------------------------

    def log(self) -> str:
        return self.log_path.read_text(encoding="utf-8", errors="replace")

    def kill_hard(self) -> None:
        """SIGKILL the supervisor and its children — the crash J5 needs.

        Kills the process GROUP: `serve` spawns web and scheduler children, and killing
        only the supervisor would leave them running against the same home, which is a
        different (and much more confusing) scenario than the crash under test.
        """
        self._guard_owned()
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.proc.wait(timeout=10)

    def _guard_owned(self) -> None:
        """Never signal a process group unless this object owns the home it runs in.

        Cheap insurance against the worst outcome a test suite can have: reaching past
        its sandbox and killing the operator's real fleet.
        """
        marker = self.home / ".topology-owned"
        if not marker.exists():
            raise RuntimeError(
                f"refusing to signal a fleet whose home {self.home} this fixture did not create"
            )

    def stop(self, *, grace_s: float = 10.0) -> None:
        if self.proc.poll() is not None:
            return
        self._guard_owned()
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        try:
            self.proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            self.kill_hard()


def _decode(raw: bytes) -> Any:
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except ValueError:
        return text


def boot(home: Path, *, api_key: str, env_overrides: dict[str, str] | None = None,
         seed: bool = True) -> ServeProcess:
    """Seed (optionally) and start `my-crew serve`; return once /health answers.

    `seed=False` reboots onto an existing home — how J5 comes back after a kill.
    """
    if seed:
        seed_home(home, api_key=api_key)
    (home / ".topology-owned").write_text("fixture-owned fleet\n", encoding="utf-8")

    port = _free_port()
    env = dict(os.environ)
    env.update({
        "MY_CREW_HOME": str(home),
        "PORT": str(port),
        "BIND_HOST": "127.0.0.1",
        "MY_CREW_TICK_INTERVAL_S": TEST_TICK_INTERVAL_S,
        "OPENROUTER_API_KEY": api_key,
    })
    env.update(env_overrides or {})
    # Auth is OFF unless a case sets a hash: an unset WEB_AUTH_PASSWORD_HASH is the
    # documented localhost-dev path, and the one case that cares sets it explicitly.

    log_path = home / "serve.log"
    handle = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        [sys.executable, "-m", "my_crew.entrypoints.mpm", "serve"],
        env=env, stdout=handle, stderr=subprocess.STDOUT,
        start_new_session=True,  # own process group, so kill/stop reaches the children
    )
    server = ServeProcess(f"http://127.0.0.1:{port}", home, proc, log_path)

    deadline = time.monotonic() + BOOT_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"serve exited rc={proc.returncode} during boot\n--- log ---\n{server.log()}"
            )
        with contextlib.suppress(Exception):
            status, _ = server.get("/health", timeout=3.0)
            if status == 200:
                return server
        time.sleep(0.25)

    server.stop()
    raise RuntimeError(
        f"serve did not answer /health within {BOOT_TIMEOUT_S}s\n--- log ---\n{server.log()}"
    )


#: Task-level states an UNATTENDED fleet will not leave on its own.
#:
#: `waiting_clarify`-equivalents belong here: measured live, an ordinary brief can run,
#: spend real money, then park asking the CEO a question. Nobody answers in a test, so
#: "settled" (finished OR parked on a human) is the only honest end condition.
SETTLED_TASK_STATES = frozenset(
    {"done", "done_with_gaps", "delivered", "cancelled", "failed", "blocked",
     "needs_decision"}
)
#: The same idea one level down — a step parked on a human holds its task at `open`.
SETTLED_STEP_STATES = frozenset({"waiting_clarify", "needs_decision", "blocked"})

#: Step states that are FINISHED rather than parked. Needed because a task can legitimately
#: end as "some steps done, the rest parked on the CEO" — measured live: a plan came back
#: `[step1 done, step2 waiting_clarify]` and nothing would ever move it again, yet a
#: parked-only rule kept polling to the full timeout and then failed a passing case.
#: Kept separate from SETTLED_STEP_STATES so `[done, running]` still keeps polling: a
#: finished step must not be mistaken for a reason to stop waiting on a live sibling.
FINISHED_STEP_STATES = frozenset({"done", "done_with_gaps", "cancelled", "failed"})


def audit_path(home: Path) -> Path:
    """The audit trail inside a fixture home.

    Built from the home rather than via `team_tasks_root()`: that helper resolves a
    module-level DATA_DIR bound at import time in THIS process, which points at the
    developer's real repo, not at the child's tmp home.
    """
    return home / ".data" / "audit" / "audit.jsonl"


def work_orders(home: Path, task_id: str) -> list[dict[str, Any]]:
    """Every work order this task wrote, oldest first.

    The work order is the only place the RESOLVED runtime tier is observable: the runner
    writes `effective_runtime` (the runtime class's own name) before the tier runs, and
    nothing in the HTTP projection or the store carries it. That matters more than it
    sounds — a fleet seeded without `agent_runtime:` runs every step native, so a case
    asserting on tool-loop behaviour would pass by never reaching the code it names. This
    is how such a case proves it was under load rather than skipped.

    Path built from `home` rather than `team_tasks_root()` for the same reason
    `audit_path` does it: that helper resolves a DATA_DIR bound at import time in THIS
    process, which points at the developer's repo instead of the child's tmp home.

    Swept across EVERY agent directory, not the coordinator's. Measured: each worker runs
    in its own child process with its own data dir, so a step assigned to `writer` writes
    its order under `.data/agents/writer/...` and nothing lands at the coordinator path.
    Reading only the coordinator path returned zero orders for every task — which would
    have made an anti-vacuity assertion fail against a product that was working.
    """
    orders = []
    for root in sorted(
        home.glob(f".data/agents/*/artifacts/team-tasks/{task_id}/work-orders")
    ):
        for path in sorted(root.glob("*.json")):
            with contextlib.suppress(ValueError, OSError):
                orders.append(json.loads(path.read_text(encoding="utf-8")))
    return sorted(orders, key=lambda o: str(o.get("created_at") or ""))


def transcript_events(home: Path, task_id: str, transcript: str) -> list[dict[str, Any]]:
    """The recorded events of one attempt, from the pointer a work order carries.

    Takes the work order's own `transcript` field rather than rebuilding the filename, so
    a rename on the writer's side surfaces as an empty read here instead of this helper
    quietly reconstructing a path that no longer matches what is written.

    Searched across every agent directory for the same reason `work_orders` is: the
    transcript sits beside the order that names it, in the writing agent's OWN data dir,
    and the caller holding that order does not know which agent ran the step.
    """
    matches = sorted(
        home.glob(f".data/agents/*/artifacts/team-tasks/{task_id}/{transcript}")
    )
    if not matches:
        return []
    events = []
    for line in matches[0].read_text(encoding="utf-8", errors="replace").splitlines():
        with contextlib.suppress(ValueError):
            events.append(json.loads(line))
    return events


def step_texts(home: Path, task_id: str) -> dict[str, str]:
    """`{artifact filename: all its prose concatenated}` for every step artifact of a task.

    Concatenates every string VALUE in the payload rather than reading `result_text` by
    name. A step's outcome artifact is written by several different call sites with
    different payload shapes (the graph's `deliver` node writes the real one; the worker's
    fallback writes a status-only payload; the stall path writes a third), so naming one
    field would make a case silently blind whenever the step took a path that spells it
    differently — and "the note is absent" is exactly what these cases assert on, so a
    blind read fails OPEN. Keyed by filename so a caller can tell a review artifact
    (`step-<n>-review-<r>.json`) from the work step's own.
    """
    root = home / ".data" / "artifacts" / "team-tasks" / task_id
    if not root.exists():
        return {}

    def _strings(node: Any) -> list[str]:
        if isinstance(node, str):
            return [node]
        if isinstance(node, dict):
            return [s for v in node.values() for s in _strings(v)]
        if isinstance(node, list):
            return [s for v in node for s in _strings(v)]
        return []

    out: dict[str, str] = {}
    for path in sorted(root.glob("step-*.json")):
        with contextlib.suppress(ValueError, OSError):
            out[path.name] = "\n".join(_strings(json.loads(path.read_text(encoding="utf-8"))))
    return out


def audit_rows(home: Path) -> list[dict[str, Any]]:
    """Every parsable row on the fixture fleet's audit trail. Corrupt lines are skipped —
    a trail is append-only from several processes, and one torn write must not blind a
    case to the rows around it."""
    path = audit_path(home)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        with contextlib.suppress(ValueError):
            rows.append(json.loads(line))
    return rows


def task_status(server: ServeProcess, task_id: str) -> dict[str, Any]:
    code, body = server.get(f"/api/control-plane/tasks/{task_id}", timeout=30)
    if code != 200:
        raise AssertionError(f"task status {task_id} returned {code}: {body!r}")
    return body


def is_settled(status: dict[str, Any]) -> bool:
    state = (status.get("state") or {}).get("status")
    if state in SETTLED_TASK_STATES:
        return True
    steps = status.get("steps") or []
    if not steps:
        return False
    statuses = [s.get("status") for s in steps]
    # No step can still move on its own, AND at least one is parked on a human. The second
    # clause matters: an all-finished set means the TASK state is the authority (it may
    # still be mid-aggregate), so let the task-level check above own that case.
    return all(
        st in SETTLED_STEP_STATES or st in FINISHED_STEP_STATES for st in statuses
    ) and any(st in SETTLED_STEP_STATES for st in statuses)


def wait_until_settled(server: ServeProcess, task_id: str, *,
                       timeout_s: float = 300.0) -> dict[str, Any]:
    """Poll a task until it finishes or parks on a human. Returns the final status."""
    return poll_until(
        lambda: (lambda st: st if is_settled(st) else None)(task_status(server, task_id)),
        timeout_s=timeout_s, interval_s=3.0,
        what=f"task {task_id} to settle (finished, or parked awaiting the CEO)",
    )


def poll_until(predicate, *, timeout_s: float, interval_s: float = 1.0, what: str = "condition"):
    """Poll until `predicate()` returns something truthy; return it.

    A hard deadline instead of a fixed sleep: journeys depend on a real tick loop and a
    real model, so their timing varies run to run, and a sleep long enough to be safe
    would make the suite unaffordable.
    """
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval_s)
    raise AssertionError(f"timed out after {timeout_s}s waiting for {what}; last={last!r}")
