"""Lớp B graph-native interrupt — the `approval_gate` node (v2 M2-P5).

A pure node placed BETWEEN `compose_report` and `deliver` in every report graph.
For `audience="external"` in GUARDED trust mode it calls LangGraph `interrupt()` so
the graph PAUSES before any delivery, checkpoint-serializes its state, and resumes
deterministically via `Command(resume="approve"|"reject")`. Approve routes to
`deliver`; reject routes to `END` (clean stop, nothing posted). In AUTONOMOUS trust
mode (v30) the gate auto-approves instead of interrupting — the run is flagged
`auto_approved` for the CEO's "đã tự duyệt" view. For `audience="internal"` the node
is a pass-through in every mode, so existing internal behavior is unchanged.

This AUGMENTS the gateway queue path (`pending_approval` + `ApprovalStore` +
`cli/mpm approve`) — it does not replace it. The one-shot worker subprocess that
cannot hold a live graph still uses the queue; the interrupt path is for an
in-process / resume-capable run (worker `--resume`).

Red lines preserved:
- The node is PURE: it only calls `interrupt()` and returns the decision into state.
  ALL side effects stay in `deliver`, which runs ONCE after an approve — so a node
  re-run on resume is harmless.
- The interrupt payload carries ONLY a non-PII action summary (report kind +
  stakeholder channel + title). No persona/project/memory ever enters it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from langgraph.graph import END
from langgraph.types import interrupt

from my_crew.agent.state import ReportState

if TYPE_CHECKING:
    from my_crew.config.reporting_config import ReportingConfig

# The state key carrying the Lớp B resume decision ("approve" | "reject"). Default
# "approve" when unset (an internal graph never sets it ⇒ always proceeds).
_DECISION_KEY = "approval_decision"
_APPROVE = "approve"


def make_approval_gate(
    audience: str, *, summary: Callable[[], str],
    report_kind: str = "", auto_approve: dict | None = None,
    settings=None,
) -> Callable[[ReportState], dict]:
    """Return the `approval_gate` node closure for the given audience.

    Internal ⇒ pass-through (returns `{}`). External ⇒ normally calls `interrupt(payload)`
    with the non-PII `summary()` and writes the resume decision into state.

    v30 autonomy-first: when `settings.trust_mode == "autonomous"` the gate auto-approves
    external delivery (no interrupt) — same state shape as the trust-ladder path, so the
    run surfaces in the CEO's "đã tự duyệt" view. `settings=None` (deps-injected callers
    that don't wire it) ⇒ GUARDED behavior — the fail-safe default is to interrupt.

    v8 M23 trust ladder: if `report_kind` is in the agent's `auto_approve.scheduled_reports`,
    the gate AUTO-APPROVES (no interrupt) — writes `approve` + an `auto_approved` flag into
    state and lets `deliver` run. deliver still posts through the gateway (Lớp A/kill-switch/
    dry-run re-apply). Absent/empty config ⇒ interrupt as before (byte-identical pre-M23)."""
    scheduled = set((auto_approve or {}).get("scheduled_reports") or ())
    autonomous = settings is not None and settings.trust_mode == "autonomous"

    def approval_gate(_state: ReportState) -> dict:
        if audience != "external":
            return {}
        if autonomous or (report_kind and report_kind in scheduled):
            # autonomous mode / trusted scheduled report → auto-deliver; the flag feeds
            # the CEO's "đã tự duyệt" view either way.
            return {_DECISION_KEY: _APPROVE, "auto_approved": True}
        decision = interrupt({"summary": summary()})
        return {_DECISION_KEY: str(decision)}

    return approval_gate


def route_after_gate(state: ReportState) -> str:
    """Conditional-edge router: deliver on approve, END on reject.

    Defaults to approve when the key is unset so an internal (pass-through) graph
    always proceeds to delivery.
    """
    decision = state.get(_DECISION_KEY, _APPROVE)
    return "deliver" if decision == _APPROVE else END


def external_summary(
    report_kind: str, audience: str, config: ReportingConfig | None
) -> Callable[[], str]:
    """Build the non-PII interrupt summary closure for the approval gate.

    Shared by all three report graphs. Carries ONLY the report kind + the
    stakeholder channel — NO profile data (persona/project/memory), preserving the
    external PII red line. Evaluated lazily and only on the external path. `config`
    is None only when an internal caller injected `deps`; the summary is unused there.
    """

    def _summary() -> str:
        if audience != "external" or config is None:
            return f"{report_kind} report"
        from my_crew.agent.audience_delivery import resolve_audience_delivery

        today = datetime.now(UTC).date().isoformat()
        channel, _ = resolve_audience_delivery(audience, report_kind, today, config)
        return f"external {report_kind} report → Slack {channel}"

    return _summary


def add_approval_gate(
    builder,
    *,
    audience: str,
    summary: Callable[[], str],
    deliver_node: str = "deliver",
    report_kind: str = "",
    auto_approve: dict | None = None,
    settings=None,
) -> None:
    """Register the `approval_gate` node + rewire `compose_report → gate → deliver|END`.

    The single wiring site shared by all report graphs (DRY). Replaces the direct
    `compose_report → deliver` edge with the gate + a conditional edge. Caller keeps
    `deliver → END` as before. `report_kind`/`auto_approve` (v8 M23) enable the trust
    ladder's scheduled-report auto-approve; `settings` (v30) enables the autonomous
    no-interrupt path; omitted ⇒ interrupt as before."""
    builder.add_node(
        "approval_gate",
        make_approval_gate(audience, summary=summary, report_kind=report_kind,
                           auto_approve=auto_approve, settings=settings),
    )
    builder.add_edge("compose_report", "approval_gate")
    builder.add_conditional_edges(
        "approval_gate", route_after_gate, {"deliver": deliver_node, END: END}
    )
