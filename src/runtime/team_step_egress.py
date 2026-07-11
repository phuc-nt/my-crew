"""Team-step external egress through the Action Gateway (v20.5 Phase 0).

The team-step graph has always had an `external_write` hook in `deliver` (designed at v12,
docstring `team_task_graph.py:44-52`) but it was never wired — `deps.external_write` was
always `None`, so a team-step could not write to the outside company at all (egress went only
through the report graphs). This module wires that hook to the per-agent Action Gateway so a
step CAN post its result out (Slack/Confluence) — but ONLY through the gateway (Lớp A/B +
audit), exactly like every report delivery. No new authority: a step egress is queued for
approval / hard-denied by the same guard chain.

v20.5 keeps it minimal + opt-in: an agent enables step egress via `team_step_egress:` in its
profile (`{channel: <slack channel id>}`). When set, `make_external_write` returns a hook that
posts the step's `result_text` to that channel through the gateway. Steps of agents without the
opt-in get `external_write=None` (byte-identical to pre-v20.5 — deliver writes only the internal
artifact). Richer per-step action metadata (post to Jira, create a page) is a follow-up.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.actions.action_gateway import ActionGateway
    from src.config.reporting_config import ReportingConfig


def make_external_write(
    gateway: ActionGateway, config: ReportingConfig, agent_id: str, channel: str, report_date: str
) -> Callable[[str], bool]:
    """Build the `external_write(result_text) -> bool` hook for team-step deliver.

    Delegates to `slack_write.deliver_report`, which routes the post through the SAME gateway
    guard chain every report uses (Lớp A hard-deny, Lớp B queue, kill-switch, dry-run, dedup,
    audit). No bypass, no new authority.

    Returns True when the gateway executed / dry-ran / deduped the post (deliver proceeds to
    write the internal artifact), False when the gateway queued it for approval (deliver
    reports `awaiting_approval`; the coordinator polls + re-runs once resolved) or hard-denied
    it (Lớp A) — the step never silently succeeds on a blocked egress.
    """
    from src.actions.slack_write import deliver_report

    def _external_write(result_text: str) -> bool:
        text = (result_text or "").strip()
        if not text:
            return True  # nothing to post → nothing to gate; let deliver proceed
        result = deliver_report(
            text,
            gateway=gateway,
            config=config,
            channel=channel,
            report_date=report_date,
            rationale=f"team-step egress from {agent_id}",
        )
        return result.status in {"executed", "dry_run", "deduplicated"}

    return _external_write
