"""Shared "who can be assigned a team-task step" computation (v12 M28b).

One function, used at BOTH gates `task_decomposition.py`'s module docstring documents:
decompose-validation time (`ops_assign_team_task.preview_assign_team_task`, before the
CEO ever sees a preview) and dispatch time (the coordinator ticker, in case the
registry/roles changed between confirm and dispatch — see `coordinator_graph.py`).
Both call sites MUST agree on the same exclusion rules, or a step could pass one gate
and silently fail (or worse, silently pass) the other.

Excluded from the assignable roster, even though they are enabled registry agents:
  - the coordinator itself (`company.yaml::coordinator_id`) — it dispatches team-task
    steps, it does not execute them.
  - the admin agent (`domain == "admin"`) — the CEO's fleet-overseer/ops-chat agent,
    not a line worker; giving it a team-task step would let a CEO brief accidentally
    grant a team-task step the admin agent's config-write ops-chat privileges.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    """What an agent can DO, as the context-crew model defines a role: the runtime tier
    (which tool loop it runs — `native` calls no tools, `create_agent` binds the read
    toolset, `deep_agent` adds the shell), web and mail access, plus the model it runs
    on. Persona is deliberately absent — two agents with the same tuple are
    interchangeable for planning purposes, and `fold_unjustified_steps` merges
    neighbouring steps split across them. `model` is the effective OpenRouter model id
    (profile override or fleet default), so a cheap-specialist agent is a different role
    from a strong-generalist one even with identical tools.

    `tier` is a field in its own right, not folded into a bool: a tools-tier agent and a
    native agent with the same web flag and model are NOT the same role — measured live,
    treating them as one folded the tools-tier research step into the native writer's
    step and the read toolset was never bound."""

    tier: str = "native"
    web: bool = False
    mail: bool = False
    model: str = ""


def agent_capability(agent_id: str) -> Capability | None:
    """Derive the capability tuple from the agent's profile. Unknown/unloadable profile ⇒
    None — an UNKNOWN role must never compare equal to another unknown role, or two
    agents nobody can read would fold into one (never raises: the consumer fails open)."""
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime_backends.protocol import runtime_kind_for

    try:
        loaded = load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    except (FileNotFoundError, RuntimeError):
        return None
    return Capability(
        tier=runtime_kind_for(loaded),
        web=bool(getattr(loaded, "web_search", False)),
        mail=bool(getattr(loaded, "gws_context", False))
        and bool(getattr(getattr(loaded, "config", None), "gws_enabled", True)),
        model=str(getattr(getattr(loaded, "config", None), "openrouter_model", "") or ""),
    )


def capability_hint(cap: Capability | None) -> str:
    """The planner-facing, user-language rendering of a role's tool boundary.

    The decomposer sees `(agent_id, domain)` and nothing else, so it cannot tell which
    agent can actually run a lookup step — measured live: a "tra lịch sử làm việc"
    step landed on a native agent one run in four, which had no history tool and could
    only report the work impossible. The hint names what the tuple's tier/web/mail
    fields let the agent DO, in the planner's language, so a step that needs a tool
    can be routed to a role that has it. Unknown capability ⇒ "" (nothing claimed)."""
    if cap is None:
        return ""
    parts: list[str] = []
    if cap.tier == "native":
        parts.append("không có công cụ — chỉ viết/suy luận trên dữ liệu được đưa")
    else:
        parts.append("có công cụ tra lịch sử làm việc nội bộ và các tích hợp")
        if cap.tier == "deep_agent":
            parts.append("chạy được shell")
    if cap.web:
        parts.append("tra được web")
    if cap.mail:
        parts.append("đọc/gửi được thư")
    return "; ".join(parts)


def planning_roster() -> list[tuple[str, str]]:
    """`assignable_staff()` with each agent's domain extended by its capability hint —
    the roster every PLANNING prompt (decompose, amend, sprint intake) renders. The
    ids are unchanged, so the validators that only need the id set keep reading
    `assignable_staff` directly."""
    staff = assignable_staff()
    caps = capability_map(a for a, _ in staff)
    out: list[tuple[str, str]] = []
    for agent_id, domain in staff:
        hint = capability_hint(caps.get(agent_id))
        out.append((agent_id, f"{domain} — {hint}" if hint else domain))
    return out


def capability_map(agent_ids) -> dict[str, Capability | None]:
    return {a: agent_capability(a) for a in agent_ids}


def assignable_staff() -> list[tuple[str, str]]:
    """`[(agent_id, domain), ...]` for every ENABLED registry agent that is neither the
    coordinator nor the admin agent — the valid `assigned_to` targets for a team-task
    step. A registry entry with no loadable profile is skipped (can't authorize a role
    we can't even read)."""
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.company import load_company
    from my_crew.runtime.registry import load_registry

    coordinator_id = load_company().coordinator_id
    roster: list[tuple[str, str]] = []
    for entry in load_registry():
        if not entry.enabled or entry.id == coordinator_id:
            continue
        try:
            loaded = load_profile(entry.id, data_dir=agent_data_dir(entry.id))
        except (FileNotFoundError, RuntimeError):
            continue
        if loaded.domain == "admin":
            continue
        roster.append((entry.id, loaded.domain))
    return roster


def sandbox_capable_ids() -> set[str]:
    """Assignable agents whose `agent_runtime.kind == "deep_agent"` — the ONLY tier a
    `needs_shell` step can actually run on (every other tier fail-closes at dispatch,
    v45). Read by the decompose/amend shell guard (v64, UAT-found): a plan carrying a
    shell step no assignable agent can run must be rejected at PLAN time with a clear
    message, not die at runtime and hand its dependents an empty handoff."""
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime_backends.protocol import runtime_kind_for

    capable: set[str] = set()
    for agent_id, _domain in assignable_staff():
        try:
            loaded = load_profile(agent_id, data_dir=agent_data_dir(agent_id))
        except (FileNotFoundError, RuntimeError):
            continue
        if runtime_kind_for(loaded) == "deep_agent":
            capable.add(agent_id)
    return capable


def validate_shell_steps(steps, *, capable_ids: set[str] | None = None) -> None:
    """v64 plan-time shell guard: every `needs_shell` step must be assigned to a
    sandbox-capable agent. Raises `DecompositionError` (CEO/retry-facing message) —
    called inside the decompose AND amend retry loops so the model first gets a chance
    to drop the flag/reassign, and the CEO gets an honest error if it never does.
    `capable_ids` is injectable for tests; None ⇒ read the live roster."""
    from my_crew.agent.task_decomposition import DecompositionError

    shell_steps = [s for s in steps if getattr(s, "needs_shell", False)]
    if not shell_steps:
        return
    capable = sandbox_capable_ids() if capable_ids is None else capable_ids
    bad = [s for s in shell_steps if s.assigned_to not in capable]
    if not bad:
        return
    ids = ", ".join(f"[{s.step_id}]→{s.assigned_to}" for s in bad)
    if capable:
        raise DecompositionError(
            f"bước cần chạy code thật ({ids}) phải giao cho agent có sandbox "
            f"({', '.join(sorted(capable))}) — đổi assigned_to hoặc bỏ needs_shell"
        )
    raise DecompositionError(
        f"bước {ids} đặt needs_shell nhưng đội CHƯA có agent nào cấu hình sandbox "
        "(agent_runtime: deep_agent) — hãy làm bước này không cần chạy code "
        "(needs_shell=false), hoặc CEO bật sandbox cho một agent trước"
    )


def agent_mail_capable(agent_id: str) -> bool:
    """Whether that agent can ACTUALLY read the owner's mailbox. Unknown profile ⇒ False.

    Mirrors the exact gate the toolset enforces (`read_only_toolset.py`): BOTH the
    per-agent `gws_context` opt-in AND the `gws_enabled` master switch. Either alone is
    not enough — `gws_enabled` also governs the write commands, and `gws_context` alone
    would claim a tool the builder refuses to bind.

    Deliberately does NOT check the runtime tier here: `resolve_step_runtime` keeps a
    `needs_mail` step off the native tier by construction, so tier is not a property of
    the AGENT the way a deep_agent's networkless sandbox is for `web_search`.
    """
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir

    try:
        loaded = load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    except (FileNotFoundError, RuntimeError):
        return False
    return bool(getattr(loaded, "gws_context", False)) and bool(
        getattr(loaded.config, "gws_enabled", True)
    )


def mail_capable_ids() -> set[str]:
    """Assignable agents that can read mail — the roster a `needs_mail` step may target."""
    return {a for a, _ in assignable_staff() if agent_mail_capable(a)}


def validate_mail_steps(steps, *, capable_ids: set[str] | None = None) -> None:
    """v92 plan-time mail guard: every `needs_mail` step must be assigned to an agent
    that can actually read the mailbox. Raises `DecompositionError` — called inside the
    decompose AND amend retry loops, so the model first gets a chance to reassign or
    drop the flag, exactly like the v64 shell guard.

    Motivation is a measured one: a mail task assigned to a mail-less agent ran to
    completion and spent $0.029 producing "em không có quyền truy cập hộp thư". Catching
    it here costs at most one extra decompose round-trip.
    `capable_ids` is injectable for tests; None ⇒ read the live roster."""
    from my_crew.agent.task_decomposition import DecompositionError

    mail_steps = [s for s in steps if getattr(s, "needs_mail", False)]
    if not mail_steps:
        return
    capable = mail_capable_ids() if capable_ids is None else capable_ids
    bad = [s for s in mail_steps if s.assigned_to not in capable]
    if not bad:
        return
    ids = ", ".join(f"[{s.step_id}]→{s.assigned_to}" for s in bad)
    if capable:
        raise DecompositionError(
            f"bước cần đọc hộp thư ({ids}) phải giao cho agent có quyền Google "
            f"({', '.join(sorted(capable))}) — đổi assigned_to hoặc bỏ needs_mail"
        )
    raise DecompositionError(
        f"bước {ids} đặt needs_mail nhưng đội CHƯA có agent nào được cấp quyền đọc thư "
        "(gws_context + gws_enabled) — hãy làm bước này không cần đọc mail "
        "(needs_mail=false), hoặc CEO cấp quyền cho một agent trước"
    )


#: Cap on the per-colleague role hint pulled from SOUL.md's first line — a targeting
#: nudge, never a persona mirror (the full SOUL only ever reaches the ANSWER call,
#: `team_task_consult.ask_colleague`, not the roster listing every step sees).
_ROLE_HINT_CHARS = 80


def roster_with_role_hints(roster: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """v14 consult targeting: enrich each `(agent_id, domain)` roster entry into
    `(agent_id, "domain — <first SOUL.md line>")` so the consult-propose LLM picks a
    colleague by what they actually DO, not just a one-word domain.

    Same read Decision C already sanctions (`team_task_consult`'s module docstring):
    a colleague's SOUL.md is an internal-only persona FILE, read RO — no Store, no
    sibling-memory, no red-line widening. Per-colleague fail-degrade: an unreadable/
    empty SOUL keeps the plain domain (this helper must never make a roster SHORTER
    than its input — targeting is advisory, availability is not). The hint is squashed
    to one line + truncated; the CALLER's prompt builder is responsible for wrapping
    the whole roster block as untrusted content (agent-authored text — see
    `team_task_consult_propose.build_propose_messages`)."""
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir

    enriched: list[tuple[str, str]] = []
    for agent_id, domain in roster:
        hint = ""
        try:
            soul = load_profile(agent_id, data_dir=agent_data_dir(agent_id)).soul
            first_line = next((ln.strip() for ln in soul.splitlines() if ln.strip()), "")
            hint = first_line.lstrip("# ").strip()[:_ROLE_HINT_CHARS]
        except Exception:  # noqa: BLE001 — hint is advisory; a bad profile keeps plain domain
            hint = ""
        enriched.append((agent_id, f"{domain} — {hint}" if hint else domain))
    return enriched


def is_assignable(agent_id: str) -> bool:
    """True iff `agent_id` is currently a valid team-task step assignee — same rules
    as `assignable_staff`, as a single-id check for the dispatch-time re-verify."""
    return any(a == agent_id for a, _ in assignable_staff())


#: Reviewer id fragments preferred over an arbitrary peer, checked case-insensitively
#: against the agent id — NOT a `role` field (the roster is `(id, domain)` only, no
#: role concept exists; Decision D deliberately anchors preference to id text instead
#: of inventing a role the registry does not have).
_REVIEWER_ID_HINTS = ("kiem", "qa", "review")


def pick_reviewer(author_id: str, roster: list[tuple[str, str]]) -> str | None:
    """Peer-review reviewer selection (Decision D) — deterministic, code-only (no LLM,
    no steering surface).

    Rule: (a) peers = every roster id EXCEPT `author_id` (coordinator/admin are already
    excluded from `roster` by `assignable_staff`); (b) among peers, prefer one whose id
    CONTAINS "kiem"/"qa"/"review" (case-insensitive) — ties broken by sorting the
    matching ids and taking the first; (c) else the alphabetically-first peer id;
    (d) `None` if `peers` is empty (1-staff fleet, or every step's only ever had this
    one author) — the CALLER (ticker) must treat `None` as "skip review, do not stall",
    never as a reason to retry or block.

    Deliberately does NOT consider `domain` at all: a same-domain peer is a fully valid
    reviewer (Finding F4 — a homogeneous-domain fleet is common; author-exclusion, not
    domain-difference, is the real security property). NEVER returns `author_id`.
    """
    peers = sorted({agent_id for agent_id, _domain in roster if agent_id != author_id})
    if not peers:
        return None
    preferred = [p for p in peers if any(hint in p.lower() for hint in _REVIEWER_ID_HINTS)]
    return preferred[0] if preferred else peers[0]
